import AVFoundation
import Speech
import SwiftUI
import UIKit

/// Talking to Sim from the phone, with Sim's own ears and Sim's own voice.
///
/// The phone records, Sim's whisper.cpp turns it into words, the words go
/// to `/api/chat` -- the same route the typed thread uses, so a spoken turn
/// and a typed one are one conversation -- and Sim's Kokoro speaks the
/// answer back as a WAV this app plays.
///
/// Two ways in:
///
///  - **Press to talk.** Tap the microphone, say a thing, and a pause ends
///    the turn. The engine stops afterwards.
///  - **Conversation.** The microphone stays open: Sim answers, and then
///    listens again, with nothing to press. "every time I want to speak to
///    sim i have to click on mic icon, i'd like to have a mode where i can
///    do interactive voice chat with sim without needing to press any
///    button" (the creator, 2026-09-25).
///
/// It used Apple's `SFSpeechRecognizer` and `AVSpeechSynthesizer` until
/// 2026-09-24: "why the voice on sim app sounds robotic ... same stt and
/// tts engines" (the creator). Three things follow from doing it Sim's way:
///
///  - The recording is made at 16 kHz mono int16, which is what
///    `voice/api.py::Audio` means by audio and what `/api/listen` reads
///    without touching ffmpeg. The tap gives whatever the hardware likes,
///    so `AVAudioConverter` does the conversion here.
///  - The turn is ended by ENERGY, in this file, not by Apple's recogniser
///    telling us it thinks the sentence is over -- so a turn ends the same
///    way whether or not Speech recognition is authorised.
///  - Apple's recogniser is still started, for the live words on screen
///    while somebody is speaking, and its transcript is NEVER what reaches
///    Sim. Whisper's is. A preview that is approximately right is worth
///    having; a preview that is silently what Sim hears is not.
///
/// Apple's synthesiser stays as a fallback for one case: Sim answered but
/// could not synthesise (no Kokoro, no ledger, house unreachable). A robot
/// voice beats silence when somebody is holding the phone waiting.
///
/// ## Not hearing itself
///
/// In conversation mode the microphone is open while Sim is speaking, so
/// the obvious failure is Sim answering its own voice. The Mac solves this
/// with an `EchoTracker` and a level gate it took the creator two attempts
/// to get right. This does the simple total thing instead: input frames are
/// DISCARDED unless the state is `waiting` or `listening`, and after
/// playback there is a short hold before listening resumes, so the tail of
/// a reply in a reverberant room is not heard as somebody starting to
/// speak. The cost is no barge-in -- talking over Sim does not stop it,
/// there is a Stop button -- and barge-in needs the engine's own voice
/// processing, which is a separate piece of work.
@MainActor
final class VoiceChat: NSObject, ObservableObject {
    /// `waiting` exists only in conversation mode: the microphone is open
    /// and nobody has started speaking yet.
    enum State: Equatable { case idle, waiting, listening, hearing, thinking, speaking }

    @Published private(set) var state: State = .idle
    /// The live preview from the phone's own recogniser while somebody
    /// speaks, replaced by what Sim actually heard.
    @Published var heard = ""
    @Published var problem: String?
    /// Speak the reply. Off means the words arrive without the voice, for
    /// a room where that matters.
    @Published var speaks = true
    /// Whose voice the last reply was in -- "kokoro", or "phone" when Sim
    /// could not make the sound and this app had to.
    @Published private(set) var engine = ""
    /// How loud the room is right now, 0...1, for the button to breathe.
    @Published private(set) var level: Double = 0
    /// The microphone stays open and the conversation continues by itself.
    @Published private(set) var conversing = false

    /// How Sim is reached. Set by the view; without it there is no voice
    /// at all, which is the honest state for an unpaired phone.
    var api: Api?
    /// Which language to ask whisper for. "" lets Sim's own
    /// `[voice] stt_language` decide, which is what the Mac does.
    var language = ""

    /// Called with what SIM heard when the person stops talking.
    var onHeard: ((String) -> Void)?

    // MARK: - Recording

    private let audio = AVAudioEngine()
    private var sink: AVAudioFormat?
    private var pcm = Data()
    private var speechSeen = false

    /// Everything below is counted in 10 ms units, because that is what one
    /// 16 kHz mono frame of 160 samples is, and time is the thing being
    /// reasoned about.
    private var quietUnits = 0
    private var loudUnits = 0
    private var spokenUnits = 0
    private var holdUnits = 0
    private var calibrateUnits = 0

    /// A pause of 1.2 s ends a turn -- Sim's own `endpoint_silence_ms`
    /// territory, and short enough that nobody thinks the phone stopped
    /// listening.
    private let silenceEnds = 120
    /// 80 ms above the bar before a turn STARTS. A door closing is loud and
    /// brief; a syllable is not.
    private let onsetNeeds = 8
    private let maxUnits = 3_000             // 30 s: a turn, not a recording
    /// The room is measured for 1.2 s before conversation mode will hear a
    /// turn in it -- the same span as the Mac's `barge_in_calibrate_ms`.
    private let calibrateFor = 120
    /// After Sim finishes speaking, 400 ms of not listening. A reply's tail
    /// in a hard-surfaced kitchen is otherwise an onset.
    private let settleFor = 40

    /// Speech sits this far above the measured floor, as a ratio. Sim's
    /// `EnergyDetector` works the same way and for the same reason: a fixed
    /// threshold is deaf in a quiet room and jumpy in a loud one.
    private let ratio = 4.0
    /// However quiet the room measures, never treat anything below this as
    /// speech. A phone on a desk at night measures almost zero, and without
    /// a floor under the floor the room's own hum becomes a turn.
    private let atLeast = 0.008
    private var floor = 0.006

    /// The last 300 ms of audio, kept so the first syllable is not lost to
    /// the 80 ms it takes to notice somebody has started.
    private var preRoll = Data()
    private let preRollBytes = 300 * 32       // 32 bytes per ms at 16 kHz int16

    private var bar: Double { max(atLeast, floor * ratio) }

    // MARK: - The phone's own recogniser, for the preview only

    private let preview = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var previewRequest: SFSpeechAudioBufferRecognitionRequest?
    private var previewTask: SFSpeechRecognitionTask?

    // MARK: - Playback

    private var player: AVAudioPlayer?
    private let fallback = AVSpeechSynthesizer()
    /// The reply being spoken, so a reply overtaken by a newer one is not
    /// played over the top of it.
    private var speaking = ""

    override init() {
        super.init()
        fallback.delegate = self
    }

    // MARK: - Permission

    /// The microphone is required. Speech recognition is not: without it
    /// there are no live words on screen, and everything else works.
    func ask() async -> Bool {
        let mic = await withCheckedContinuation { go in
            AVAudioApplication.requestRecordPermission { go.resume(returning: $0) }
        }
        guard mic else {
            problem = "The microphone is off for this app. Settings › Privacy › Microphone."
            return false
        }
        _ = await withCheckedContinuation { go in
            SFSpeechRecognizer.requestAuthorization { go.resume(returning: $0) }
        }
        return true
    }

    // MARK: - Conversation mode

    /// Open the microphone and keep it open: Sim answers, then listens
    /// again, with nothing to press.
    func converse() async {
        guard !conversing else { return }
        guard await ask() else { return }
        guard api != nil else {
            problem = "This phone is not paired with Sim yet."
            return
        }
        conversing = true
        // A conversation is worth keeping the screen awake for; locking
        // mid-sentence is how a hands-free mode stops being hands-free.
        UIApplication.shared.isIdleTimerDisabled = true
        guard startEngine() else {
            conversing = false
            UIApplication.shared.isIdleTimerDisabled = false
            return
        }
        // Measure the room before hearing a turn in it.
        calibrateUnits = calibrateFor
        armWaiting()
    }

    /// Close the microphone and stop the conversation.
    func endConverse() {
        conversing = false
        UIApplication.shared.isIdleTimerDisabled = false
        stopSpeaking()
        stopEngine()
        // Hand the audio session back, so whatever was ducked comes back up
        // and nothing holds the microphone after the conversation is over.
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        heard = ""
        state = .idle
    }

    /// The app left the screen. This app has the `audio` background mode --
    /// it needs it to finish speaking a reply -- so nothing would otherwise
    /// close an open microphone, and a hands-free mode that keeps listening
    /// after somebody has put the phone away is not one anybody asked for.
    func leftTheScreen() {
        guard conversing else { return }
        endConverse()
    }

    // MARK: - Press to talk

    /// One turn, because somebody pressed the button. The engine stops when
    /// the turn is over.
    func start() async {
        guard state == .idle || state == .speaking else { return }
        stopSpeaking()
        guard await ask() else { return }
        guard startEngine() else { return }
        // No calibration and no onset wait: the button IS the onset. A
        // person who has just pressed it is already talking.
        beginUtterance()
    }

    /// Stop listening and throw the recording away. In conversation mode
    /// this returns to waiting rather than closing the microphone.
    func cancel() {
        previewStop()
        pcm.removeAll(keepingCapacity: true)
        heard = ""
        if conversing { armWaiting() } else { stopEngine(); state = .idle }
    }

    // MARK: - The audio engine

    private func startEngine() -> Bool {
        guard !audio.isRunning else { return true }
        do {
            let session = AVAudioSession.sharedInstance()
            // ONE category for the whole conversation, capture and
            // playback together: switching to `.playback` to speak would
            // tear down the running input and the next turn would be deaf.
            try session.setCategory(.playAndRecord, mode: .spokenAudio,
                                    options: [.duckOthers, .defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let input = audio.inputNode
            let source = input.outputFormat(forBus: 0)
            guard let sim = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000,
                                          channels: 1, interleaved: true),
                  let converter = AVAudioConverter(from: source, to: sim) else {
                problem = "This phone will not record at 16 kHz mono, which is the audio Sim reads."
                return false
            }
            sink = sim
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 2_048, format: source) { [weak self] buffer, _ in
                guard let self else { return }
                // The preview wants the hardware's own format.
                self.previewRequest?.append(buffer)
                guard let converted = Self.convert(buffer, with: converter, to: sim) else { return }
                Task { @MainActor in self.took(converted) }
            }
            audio.prepare()
            try audio.start()
            return true
        } catch {
            problem = error.localizedDescription
            state = .idle
            return false
        }
    }

    private func stopEngine() {
        previewStop()
        audio.inputNode.removeTap(onBus: 0)
        if audio.isRunning { audio.stop() }
        sink = nil
        level = 0
        preRoll.removeAll(keepingCapacity: false)
    }

    /// Back to an open microphone with nobody speaking, after a reply or a
    /// cancelled turn.
    private func armWaiting() {
        pcm.removeAll(keepingCapacity: true)
        preRoll.removeAll(keepingCapacity: true)
        speechSeen = false
        quietUnits = 0; loudUnits = 0; spokenUnits = 0
        holdUnits = settleFor
        level = 0
        state = .waiting
    }

    private func beginUtterance() {
        pcm.removeAll(keepingCapacity: true)
        // The pre-roll first, so the first syllable survives the time it
        // took to notice it.
        pcm.append(preRoll)
        preRoll.removeAll(keepingCapacity: true)
        speechSeen = false
        quietUnits = 0; spokenUnits = 0
        heard = ""; engine = ""
        previewStart()
        state = .listening
    }

    /// One converted buffer: watch the energy, and decide what it means for
    /// the state we are in.
    private func took(_ buffer: AVAudioPCMBuffer) {
        guard let samples = buffer.int16ChannelData else { return }
        let count = Int(buffer.frameLength)
        guard count > 0 else { return }
        let units = max(1, count / 160)
        var sum = 0.0
        for i in 0..<count {
            let value = Double(samples[0][i]) / 32_768.0
            sum += value * value
        }
        let rms = (sum / Double(count)).squareRoot()

        switch state {
        case .waiting:
            level = min(1.0, rms * 12)
            keepPreRoll(samples, count)
            // Settling after Sim spoke, or still measuring the room. Both
            // are learning time, not listening time.
            if holdUnits > 0 { holdUnits -= units; learnFloor(rms); return }
            if calibrateUnits > 0 { calibrateUnits -= units; learnFloor(rms); return }
            if rms >= bar {
                loudUnits += units
                if loudUnits >= onsetNeeds { loudUnits = 0; beginUtterance() }
            } else {
                loudUnits = 0
                learnFloor(rms)
            }

        case .listening:
            level = min(1.0, rms * 12)
            pcm.append(UnsafeBufferPointer(start: samples[0], count: count))
            spokenUnits += units
            if rms >= bar {
                speechSeen = true
                quietUnits = 0
            } else {
                quietUnits += units
                if quietUnits >= silenceEnds { finish(); return }
            }
            if spokenUnits >= maxUnits { finish() }

        case .idle, .hearing, .thinking, .speaking:
            // Sim is transcribing, thinking, or TALKING. Nothing the
            // microphone hears now is a turn -- which is also how Sim
            // avoids answering its own voice here.
            return
        }
    }

    /// The floor follows the room: down quickly, up slowly, so a passing
    /// lorry does not leave Sim deaf for the next minute.
    private func learnFloor(_ rms: Double) {
        floor = rms < floor ? (floor * 0.7 + rms * 0.3) : (floor * 0.97 + rms * 0.03)
    }

    private func keepPreRoll(_ samples: UnsafePointer<UnsafeMutablePointer<Int16>>, _ count: Int) {
        preRoll.append(UnsafeBufferPointer(start: samples[0], count: count))
        if preRoll.count > preRollBytes { preRoll.removeFirst(preRoll.count - preRollBytes) }
    }

    /// The tap's format is the hardware's; Sim reads 16 kHz mono int16.
    private nonisolated static func convert(_ buffer: AVAudioPCMBuffer,
                                            with converter: AVAudioConverter,
                                            to format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let ratio = format.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return nil }
        var given = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if given { status.pointee = .noDataNow; return nil }
            given = true
            status.pointee = .haveData
            return buffer
        }
        return error == nil && out.frameLength > 0 ? out : nil
    }

    // MARK: - Handing the turn over

    /// Stop recording and send what was said to Sim's recogniser.
    func finish() {
        guard state == .listening else { return }
        previewStop()
        if !conversing { stopEngine() }
        guard speechSeen, pcm.count > 3_200 else {       // under 0.1 s is a tap, not a turn
            settle()
            return
        }
        state = .hearing
        let wav = Self.wav(pcm)
        let language = self.language
        guard let api else {
            problem = "This phone is not paired with Sim yet."
            settle()
            return
        }
        Task { @MainActor in
            do {
                let got = try await api.listen(wav: wav, language: language)
                let said = (got.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !said.isEmpty else {
                    // Whisper heard nothing in it -- a cough, a chair, the
                    // room. Say nothing and listen again rather than
                    // sending the preview: what reaches Sim is what Sim
                    // heard, always.
                    heard = ""
                    settle()
                    return
                }
                heard = said
                state = .thinking
                onHeard?(said)
            } catch {
                problem = (error as? Api.Failure)?.detail ?? error.localizedDescription
                settle()
            }
        }
    }

    /// The end of a turn, however it ended: listening again in a
    /// conversation, idle otherwise.
    private func settle() {
        if conversing { armWaiting() } else { state = .idle }
    }

    /// Sim was asked and could not answer.
    func failed() { settle() }

    // MARK: - Speaking

    /// Sim's own voice, fetched as audio and played here. Apple's
    /// synthesiser only if that fails.
    func say(_ text: String) {
        guard speaks, !text.isEmpty else {
            settle()
            return
        }
        speaking = text
        state = .speaking
        guard let api else { sayWithThePhone(text); return }
        Task { @MainActor in
            do {
                let spoken = try await api.say(text)
                guard state == .speaking, speaking == text else { return }   // stopped meanwhile
                try play(spoken.wav)
                engine = spoken.engine.isEmpty ? "sim" : spoken.engine
            } catch {
                // Not shown as a problem: the sentence is still said, and
                // a banner every time Kokoro is cold would be noise.
                sayWithThePhone(text)
            }
        }
    }

    private func play(_ wav: Data) throws {
        // The category is NOT changed here. In a conversation the engine is
        // running under `.playAndRecord` and switching it would deafen the
        // next turn; outside one there is nothing recording to disturb.
        if !audio.isRunning {
            let session = AVAudioSession.sharedInstance()
            try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try? session.setActive(true)
        }
        let player = try AVAudioPlayer(data: wav)
        player.delegate = self
        self.player = player
        player.prepareToPlay()
        player.play()
    }

    private func sayWithThePhone(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.postUtteranceDelay = 0.1
        if !audio.isRunning {
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try? AVAudioSession.sharedInstance().setActive(true)
        }
        engine = "phone"
        state = .speaking
        fallback.speak(utterance)
    }

    func stopSpeaking() {
        player?.stop(); player = nil
        if fallback.isSpeaking { fallback.stopSpeaking(at: .immediate) }
        speaking = ""
        if state == .speaking { settle() }
    }

    // MARK: - The preview recogniser

    private func previewStart() {
        guard let preview, preview.isAvailable,
              SFSpeechRecognizer.authorizationStatus() == .authorized else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if preview.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        previewRequest = request
        previewTask = preview.recognitionTask(with: request) { [weak self] result, _ in
            guard let result else { return }
            Task { @MainActor in
                // Only while listening: once Sim has answered, its words
                // stand and a late preview must not overwrite them.
                guard self?.state == .listening else { return }
                self?.heard = result.bestTranscription.formattedString
            }
        }
    }

    private func previewStop() {
        previewRequest?.endAudio()
        previewTask?.cancel()
        previewRequest = nil
        previewTask = nil
    }

    // MARK: - WAV

    /// `pcm` (16 kHz mono int16) as a WAV file, which is what
    /// `/api/listen` reads straight through without ffmpeg.
    static func wav(_ pcm: Data, sampleRate: Int = 16_000) -> Data {
        var out = Data()
        func ascii(_ s: String) { out.append(contentsOf: Array(s.utf8)) }
        func u32(_ v: Int) { var l = UInt32(v).littleEndian; withUnsafeBytes(of: &l) { out.append(contentsOf: $0) } }
        func u16(_ v: Int) { var l = UInt16(v).littleEndian; withUnsafeBytes(of: &l) { out.append(contentsOf: $0) } }
        ascii("RIFF"); u32(36 + pcm.count); ascii("WAVE")
        ascii("fmt "); u32(16); u16(1); u16(1)
        u32(sampleRate); u32(sampleRate * 2); u16(2); u16(16)
        ascii("data"); u32(pcm.count)
        out.append(pcm)
        return out
    }
}

extension VoiceChat: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                       didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in if self.state == .speaking { self.settle() } }
    }
}

extension VoiceChat: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully: Bool) {
        Task { @MainActor in
            self.player = nil
            if self.state == .speaking { self.settle() }
        }
    }
}
