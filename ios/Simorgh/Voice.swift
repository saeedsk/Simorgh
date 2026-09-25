import AVFoundation
import Speech
import SwiftUI

/// Talking to Sim from the phone.
///
/// Speech goes to text ON THIS DEVICE (`SFSpeechRecognizer`, forced
/// on-device where iOS offers it), the text goes to `/api/chat` -- the same
/// route the typed thread uses, so a spoken turn and a typed one are the
/// same conversation -- and the answer is spoken back by
/// `AVSpeechSynthesizer`.
///
/// Why not Sim's own ears and voice: Sim's whisper and Kokoro are on the
/// Mac, and reaching them needs the second `VoiceSession` and the audio
/// socket (`voice/remote.py`, stage 12 item 5) that do not exist yet.
/// Waiting for those would mean no voice at all, and this is real voice
/// chat today: press, speak, hear the answer. When item 5 lands, what
/// changes is WHOSE ears and voice -- not this screen.
@MainActor
final class VoiceChat: NSObject, ObservableObject {
    enum State: Equatable { case idle, listening, thinking, speaking }

    @Published private(set) var state: State = .idle
    @Published var heard = ""
    @Published var problem: String?
    /// Speak the reply. Off means the words arrive without the voice, for
    /// a room where that matters.
    @Published var speaks = true

    private let recogniser = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let synth = AVSpeechSynthesizer()
    private var silence: Timer?

    /// Called with the final transcript when the person stops talking.
    var onHeard: ((String) -> Void)?

    override init() {
        super.init()
        synth.delegate = self
    }

    // MARK: - Permission

    func ask() async -> Bool {
        let speech = await withCheckedContinuation { go in
            SFSpeechRecognizer.requestAuthorization { go.resume(returning: $0) }
        }
        guard speech == .authorized else {
            problem = "Speech recognition is off for this app. Settings › Privacy › Speech Recognition."
            return false
        }
        let mic = await withCheckedContinuation { go in
            AVAudioApplication.requestRecordPermission { go.resume(returning: $0) }
        }
        if !mic { problem = "The microphone is off for this app. Settings › Privacy › Microphone." }
        return mic
    }

    // MARK: - Listening

    func start() async {
        guard state == .idle || state == .speaking else { return }
        stopSpeaking()
        guard await ask() else { return }
        guard let recogniser, recogniser.isAvailable else {
            problem = "Speech recognition is not available right now."
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .spokenAudio,
                                    options: [.duckOthers, .defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            // On-device when iOS can: nothing said in this house should
            // need a round trip to Apple to become text.
            if recogniser.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
            self.request = request

            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak request] buffer, _ in
                request?.append(buffer)
            }
            engine.prepare()
            try engine.start()

            heard = ""
            state = .listening
            task = recogniser.recognitionTask(with: request) { [weak self] result, error in
                guard let self else { return }
                Task { @MainActor in
                    if let result {
                        self.heard = result.bestTranscription.formattedString
                        // A pause ends the turn, the way Sim's own
                        // endpointer does -- holding a button down to talk
                        // is not how people speak to a room.
                        self.armSilence()
                    }
                    if error != nil || (result?.isFinal ?? false) { self.finish() }
                }
            }
        } catch {
            problem = error.localizedDescription
            state = .idle
        }
    }

    private func armSilence() {
        silence?.invalidate()
        silence = Timer.scheduledTimer(withTimeInterval: 1.4, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.finish() }
        }
    }

    /// Stop listening and hand over whatever was heard.
    func finish() {
        silence?.invalidate(); silence = nil
        guard state == .listening else { return }
        engine.inputNode.removeTap(onBus: 0)
        if engine.isRunning { engine.stop() }
        request?.endAudio()
        task?.cancel()
        request = nil; task = nil

        let said = heard.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !said.isEmpty else {
            state = .idle
            return
        }
        state = .thinking
        onHeard?(said)
    }

    /// Stop listening and throw the words away.
    func cancel() {
        silence?.invalidate(); silence = nil
        engine.inputNode.removeTap(onBus: 0)
        if engine.isRunning { engine.stop() }
        request?.endAudio(); task?.cancel()
        request = nil; task = nil
        heard = ""
        state = .idle
    }

    // MARK: - Speaking

    func say(_ text: String) {
        guard speaks, !text.isEmpty else {
            state = .idle
            return
        }
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.postUtteranceDelay = 0.1
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio,
                                                            options: [.duckOthers])
            try AVAudioSession.sharedInstance().setActive(true)
        } catch { /* speaking is a courtesy; a session that will not set is not fatal */ }
        state = .speaking
        synth.speak(utterance)
    }

    func stopSpeaking() {
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        if state == .speaking { state = .idle }
    }

    func failed() { state = .idle }
}

extension VoiceChat: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                       didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in if self.state == .speaking { self.state = .idle } }
    }
}
