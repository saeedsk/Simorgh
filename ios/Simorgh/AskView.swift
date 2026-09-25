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
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(.tertiary)
            Text("Ask Sim anything").font(.headline)
            Text("It can see the house, read your mail, and start work for you.")
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
        if turn.failed { return Color.red.opacity(0.85) }
        return turn.mine ? Color.accentColor : Color(.secondarySystemBackground)
    }

    private var composer: some View {
        VStack(spacing: 0) {
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
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 30))
                        .symbolRenderingMode(.hierarchical)
                }
                .disabled(sendable == false)
                .opacity(sendable ? 1 : 0.4)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)
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
        waiting = true
        Task {
            defer { waiting = false }
            do {
                let reply = try await Api(baseURL: store.baseURL, token: store.token)
                    .chat(text, session: session)
                let said = (reply.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                // An empty reply is Sim choosing silence (QUIET) or a
                // floored turn. Saying nothing here would look like the app
                // losing the message.
                turns.append(Turn(mine: false, text: said.isEmpty ? "Sim had nothing to say." : said))
            } catch {
                turns.append(Turn(mine: false, text: error.localizedDescription, failed: true))
            }
        }
    }
}
