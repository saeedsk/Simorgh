import SwiftUI

/// The thread. One `session_id` for the life of the app so Sim's memory
/// groups this as one conversation rather than a stranger each time.
struct AskView: View {
    @EnvironmentObject var store: Store
    @State private var typed = ""
    @State private var turns: [Turn] = []
    @State private var waiting = false
    @State private var session = "iphone-" + UUID().uuidString.prefix(8).lowercased()
    @FocusState private var writing: Bool
    @StateObject private var voice = VoiceChat()
    @Environment(\.scenePhase) private var phase

    struct Turn: Identifiable {
        let id = UUID()
        let mine: Bool
        let text: String
        let at = Date()
        var failed = false
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                thread
                composer
            }
            .background(Color(.systemGroupedBackground))
            .onChange(of: phase) { _, now in
                if now != .active { voice.leftTheScreen() }
            }
            .navigationTitle("Ask")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                // Above the keyboard, which is the only place a thumb
                // looks for it. Without this the keyboard never left the
                // screen (the creator, 2026-09-25).
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { writing = false }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { voice.speaks.toggle(); if !voice.speaks { voice.stopSpeaking() } } label: {
                        Image(systemName: voice.speaks ? "speaker.wave.2" : "speaker.slash")
                    }
                    .tint(voice.speaks ? Brand.gold : .secondary)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if !turns.isEmpty {
                        Button { turns.removeAll() } label: { Image(systemName: "trash") }
                            .tint(.secondary)
                    }
                }
            }
        }
    }

    private var thread: some View {
        ScrollViewReader { scroll in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    if turns.isEmpty { empty }
                    ForEach(turns) { turn in
                        bubble(turn).id(turn.id)
                    }
                    if waiting {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text("Sim is thinking…").font(.footnote).foregroundStyle(.secondary)
                        }
                        .padding(.leading, 4)
                        .id("waiting")
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 16)
            }
            // A drag on the thread puts the keyboard away, which is what a
            // thumb tries first.
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: turns.count) {
                withAnimation { scroll.scrollTo(turns.last?.id ?? UUID(), anchor: .bottom) }
            }
            .onChange(of: waiting) {
                if waiting { withAnimation { scroll.scrollTo("waiting", anchor: .bottom) } }
            }
        }
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Feather(size: 72)
            Text("Ask Sim anything")
                .font(.system(.title3, design: .serif, weight: .semibold))
            Text("Type, or tap the microphone and just talk.")
                .font(.footnote).foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }

    private func bubble(_ turn: Turn) -> some View {
        HStack(alignment: .bottom, spacing: 6) {
            if turn.mine { Spacer(minLength: 48) }
            VStack(alignment: turn.mine ? .trailing : .leading, spacing: 3) {
                Text(turn.text)
                    .textSelection(.enabled)
                    .padding(.horizontal, 13)
                    .padding(.vertical, 9)
                    .background(background(for: turn))
                    .foregroundStyle(turn.mine ? Color.white : Color.primary)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                Text(turn.at, style: .time)
                    .font(.caption2).foregroundStyle(.tertiary)
                    .padding(.horizontal, 4)
            }
            if !turn.mine { Spacer(minLength: 48) }
        }
    }

    private func background(for turn: Turn) -> Color {
        if turn.failed { return Brand.crimson.opacity(0.9) }
        return turn.mine ? Brand.lapis : Color(.secondarySystemBackground)
    }

    private var composer: some View {
        VStack(spacing: 0) {
            if voice.state != .idle || voice.conversing { voiceBar }
            Divider()
            HStack(alignment: .bottom, spacing: 8) {
                TextField("Message", text: $typed, axis: .vertical)
                    .lineLimit(1...5)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .focused($writing)
                    .submitLabel(.send)
                    .onSubmit(send)
                if typed.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    // Hands free: the microphone stays open and Sim
                    // listens again after every answer. Separate from the
                    // microphone button on purpose -- one is "I want to say
                    // one thing", the other is "let us talk" -- and the
                    // creator asked for the second: "I'd like to have a
                    // mode where i can do interactive voice chat with sim
                    // without needing to press any button" (2026-09-25).
                    Button {
                        if voice.conversing { voice.endConverse() } else { Task { await converse() } }
                    } label: {
                        Image(systemName: voice.conversing
                              ? "waveform.circle.fill" : "waveform.circle")
                            .font(.system(size: 30))
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(voice.conversing ? Brand.gold : .secondary)
                    }
                    .disabled(waiting)
                    .accessibilityLabel(voice.conversing ? "End the conversation" : "Start a conversation")

                    Button {
                        Task { await talk() }
                    } label: {
                        Image(systemName: voice.state == .listening ? "stop.circle.fill" : "mic.circle.fill")
                            .font(.system(size: 30))
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(voice.state == .listening ? Brand.crimson : Brand.lapis)
                            // Breathes with the room, so somebody can see
                            // the phone is hearing them before any words
                            // appear -- the recording is sent to Sim in
                            // one piece, so there is a beat with nothing
                            // on screen and a still button reads as dead.
                            .scaleEffect(voice.state == .listening ? 1 + 0.12 * voice.level : 1)
                            .animation(.easeOut(duration: 0.12), value: voice.level)
                    }
                    .disabled(waiting || voice.state == .hearing || voice.conversing)
                } else {
                    Button(action: send) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 30))
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(Brand.lapis)
                    }
                    .disabled(sendable == false)
                    .opacity(sendable ? 1 : 0.4)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)
        }
    }

    /// What the microphone is doing, in words rather than a pulsing dot:
    /// "listening" and "thinking" are different waits and a person who
    /// cannot tell them apart will talk over the answer.
    private var voiceBar: some View {
        HStack(spacing: 10) {
            switch voice.state {
            case .listening:
                Image(systemName: "waveform").foregroundStyle(Brand.crimson).symbolEffect(.variableColor)
                Text(voice.heard.isEmpty ? "Listening…" : voice.heard)
                    .font(.footnote).lineLimit(2)
                    // A preview from the phone's own recogniser. What
                    // reaches Sim is what Sim's whisper hears, which
                    // arrives a moment later and replaces this.
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Stop") { voice.cancel() }.font(.footnote)
            case .waiting:
                // The microphone is open and nobody is talking. A live
                // level, not a spinner: the thing being waited for is the
                // person, and a spinner would suggest Sim is busy.
                Image(systemName: "ear")
                    .foregroundStyle(Brand.gold)
                    .scaleEffect(1 + 0.25 * voice.level)
                    .animation(.easeOut(duration: 0.12), value: voice.level)
                Text("Listening — just talk").font(.footnote).foregroundStyle(.secondary)
                Spacer()
                Button("End") { voice.endConverse() }.font(.footnote)
            case .hearing:
                // Sim's whisper has the recording. Named separately from
                // "thinking" because it is a different wait, and the word
                // on screen is the only way to tell them apart.
                ProgressView().controlSize(.small)
                Text(voice.heard.isEmpty ? "Sim is listening back…" : "Sim is listening back…  \u{201c}\(voice.heard)\u{201d}")
                    .font(.footnote).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
            case .thinking:
                ProgressView().controlSize(.small)
                Text("Sim is thinking…").font(.footnote).foregroundStyle(.secondary)
                Spacer()
            case .speaking:
                Image(systemName: "speaker.wave.2.fill").foregroundStyle(Brand.gold)
                Text(voice.engine == "phone" ? "Speaking (this phone's voice)" : "Sim is speaking")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
                Button("Stop") { voice.stopSpeaking() }.font(.footnote)
            case .idle:
                EmptyView()
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 8)
        .background(Color(.secondarySystemBackground))
    }

    /// Start a hands-free conversation. Same plumbing as `talk()` -- the
    /// difference is that `VoiceChat` reopens the microphone after each
    /// answer instead of going idle.
    private func converse() async {
        writing = false
        voice.api = Api(baseURL: store.baseURL, token: store.token)
        voice.onHeard = { said in
            turns.append(Turn(mine: true, text: said))
            Task { await ask(said) }
        }
        await voice.converse()
    }

    private func talk() async {
        writing = false
        if voice.state == .listening { voice.finish(); return }
        // Sim's own recogniser and Sim's own voice, which means the voice
        // chat needs the connection the rest of this screen uses.
        voice.api = Api(baseURL: store.baseURL, token: store.token)
        voice.onHeard = { said in
            turns.append(Turn(mine: true, text: said))
            Task { await ask(said) }
        }
        await voice.start()
    }

    /// One turn, however it arrived. Typing and talking are the same
    /// conversation -- the same `session_id`, so Sim's memory groups them
    /// as one rather than two strangers.
    private func ask(_ text: String) async {
        waiting = true
        defer { waiting = false }
        do {
            let reply = try await Api(baseURL: store.baseURL, token: store.token)
                .chat(text, session: session)
            let said = (reply.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let shown = said.isEmpty ? "Sim had nothing to say." : said
            turns.append(Turn(mine: false, text: shown))
            if said.isEmpty { voice.failed() } else { voice.say(said) }
        } catch {
            turns.append(Turn(mine: false, text: error.localizedDescription, failed: true))
            voice.failed()
        }
    }

    private var sendable: Bool {
        !typed.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !waiting
    }

    private func send() {
        let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !waiting else { return }
        typed = ""
        turns.append(Turn(mine: true, text: text))
        // An empty reply is Sim choosing silence (QUIET) or a floored turn,
        // and `ask` says so rather than leaving the screen looking as
        // though the app lost the message.
        Task { await ask(text) }
    }
}
