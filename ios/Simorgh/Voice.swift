import AVFoundation
import Speech
import SwiftUI

/// Talking to Sim from the phone, with Sim's own ears and Sim's own voice.
///
/// The phone records, Sim's whisper.cpp turns it into words, the words go
/// to `/api/chat` -- the same route the typed thread uses, so a spoken turn
/// and a typed one are one conversation -- and Sim's Kokoro speaks the
/// answer back as a WAV this app plays.
///
/// It used Apple's `SFSpeechRecognizer` and `AVSpeechSynthesizer` until
/// 2026-09-24: "why the voice on sim app sounds robotic, I want to have
/// same voice chat experience as I have on mac with same stt and tts
/// engines" (the creator). Three things follow from doing it Sim's way:
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
@MainActor
final class VoiceChat: NSObject, ObservableObject {
    enum State: Equatable { case idle, listening, hearing, thinking, speaking }

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
    private var converter: AVAudioConverter?
    private var pcm = Data()
    private var speechSeen = false
    private var quietFrames = 0
    private var frames = 0

    /// One 16 kHz mono int16 frame is 10 ms of audio here; these are in
    /// frames so they read as time. A pause of 1.2 s ends a turn -- Sim's
    /// own `endpoint_silence_ms` default territory, and short enough that
    /// nobody thinks the phone has stopped listening.
    private let silenceEnds = 120
    private let maxFrames = 3_000            // 30 s: a turn, not a recording
    /// Below this RMS (of full scale) a frame is silence. Deliberately low:
    /// a phone held at arm's length in a kitchen is quiet, and cutting
    /// somebody off mid-sentence is worse than a second of trailing hiss.
    private let speechAbove: Double = 0.012

    // MARK: - The phone's own recogniser, for the preview only

    private let preview = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var previewRequest: SFSpeechAudioBufferRecognitionRequest?
    private var previewTask: SFSpeechRecognitionTask?

    // MARK: - Playback

    private var player: AVAudioPlayer?
    private let fallback = AVSpeechSynthesizer()
    /// The reply being spoken, so a failure part-way can still be said by
    /// the phone rather than dropped.
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

    // MARK: - Listening

    func start() async {
        guard state == .idle || state == .speaking else { return }
        stopSpeaking()
        guard await ask() else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .spokenAudio,
                                    options: [.duckOthers, .defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let input = audio.inputNode
            let source = input.outputFormat(forBus: 0)
            guard let sim = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000,
                                          channels: 1, interleaved: true),
                  let converter = AVAudioConverter(from: source, to: sim) else {
                problem = "This phone will not record at 16 kHz mono, which is the audio Sim reads."
                return
            }
            self.converter = converter

            startPreview()
            pcm.removeAll(keepingCapacity: true)
            speechSeen = false; quietFrames = 0; frames = 0
            heard = ""; engine = ""; level = 0

            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 2_048, format: source) { [weak self] buffer, _ in
                guard let self else { return }
                self.previewRequest?.append(buffer)
                guard let converted = Self.convert(buffer, with: converter, to: sim) else { return }
                Task { @MainActor in self.took(converted) }
            }
            audio.prepare()
            try audio.start()
            state = .listening
        } catch {
            problem = error.localizedDescription
            state = .idle
        }
    }

    /// One converted buffer: keep the bytes, watch the energy, and decide
    /// whether the turn is over.
    private func took(_ buffer: AVAudioPCMBuffer) {
        guard state == .listening, let samples = buffer.int16ChannelData else { return }
        let count = Int(buffer.frameLength)
        guard count > 0 else { return }
        var sum = 0.0
        for i in 0..<count {
            let value = Double(samples[0][i]) / 32_768.0
            sum += value * value
        }
        let rms = (sum / Double(count)).squareRoot()
        level = min(1.0, rms * 12)
        pcm.append(UnsafeBufferPointer(start: samples[0], count: count))
        frames += 1

        if rms >= speechAbove {
            speechSeen = true
            quietFrames = 0
        } else if speechSeen {
            quietFrames += count / 160          // 160 samples = 10 ms at 16 kHz
            if quietFrames >= silenceEnds { finish() }
        }
        if frames * (count / 160) >= maxFrames { finish() }
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

    /// Stop recording and send what was said to Sim's recogniser.
    func finish() {
        guard state == .listening else { return }
        stopRecording()
        guard speechSeen, pcm.count > 3_200 else {       // under 0.1 s is a tap, not a turn
            state = .idle
            return
        }
        state = .hearing
        let wav = Self.wav(pcm)
        let language = self.language
        guard let api else {
            problem = "This phone is not paired with Sim yet."
            state = .idle
            return
        }
        Task { @MainActor in
            do {
                let got = try await api.listen(wav: wav, language: language)
                let said = (got.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !said.isEmpty else {
                    // Whisper heard nothing in it. Say so rather than
                    // sending the preview: what reaches Sim is what Sim
                    // heard, always.
                    heard = ""
                    state = .idle
                    return
                }
                heard = said
                state = .thinking
                onHeard?(said)
            } catch {
                problem = (error as? Api.Failure)?.detail ?? error.localizedDescription
                state = .idle
            }
        }
    }

    /// Stop listening and throw the recording away.
    func cancel() {
        stopRecording()
        pcm.removeAll(keepingCapacity: false)
        heard = ""
        state = .idle
    }

    private func stopRecording() {
        audio.inputNode.removeTap(onBus: 0)
        if audio.isRunning { audio.stop() }
        previewRequest?.endAudio()
        previewTask?.cancel()
        previewRequest = nil; previewTask = nil
        converter = nil
        level = 0
    }

    private func startPreview() {
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

    // MARK: - Speaking

    /// Sim's own voice, fetched as audio and played here. Apple's
    /// synthesiser only if that fails.
    func say(_ text: String) {
        guard speaks, !text.isEmpty else {
            state = .idle
            return
        }
        speaking = text
        state = .speaking
        guard let api else { sayWithThePhone(text); return }
        Task { @MainActor in
            do {
                let spoken = try await api.say(text)
                guard state == .speaking, speaking == text else { return }   // barged in meanwhile
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
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)
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
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? AVAudioSession.sharedInstance().setActive(true)
        engine = "phone"
        state = .speaking
        fallback.speak(utterance)
    }

    func stopSpeaking() {
        player?.stop(); player = nil
        if fallback.isSpeaking { fallback.stopSpeaking(at: .immediate) }
        speaking = ""
        if state == .speaking { state = .idle }
    }

    func failed() { state = .idle }

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
        Task { @MainActor in if self.state == .speaking { self.state = .idle } }
    }
}

extension VoiceChat: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully: Bool) {
        Task { @MainActor in
            self.player = nil
            if self.state == .speaking { self.state = .idle }
        }
    }
}
