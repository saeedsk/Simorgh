import SwiftUI

/// The thread. One `session_id` for the life of the app so Sim's memory
/// groups this as one conversation rather than a stranger each time.
struct AskView: View {
    @EnvironmentObject var store: Store
    @State private var typed = ""
    @State private var turns: [Turn] = []
    @State private var waiting = false
    @State private var session = "iphone-" + UUID().uuidString.prefix(8).lowercased()

    struct Turn: Identifiable {
        let id = UUID()
        let mine: Bool
        let text: String
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollViewReader { scroll in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            ForEach(turns) { turn in
                                HStack {
                                    if turn.mine { Spacer(minLength: 40) }
                                    Text(turn.text)
                                        .padding(10)
                                        .background(turn.mine ? Color.accentColor.opacity(0.15)
                                                              : Color.secondary.opacity(0.12))
                                        .clipShape(RoundedRectangle(cornerRadius: 12))
                                    if !turn.mine { Spacer(minLength: 40) }
                                }
                                .id(turn.id)
                            }
                            if waiting {
                                HStack { ProgressView(); Text("thinking…").foregroundStyle(.secondary) }
                            }
                        }
                        .padding()
                    }
                    .onChange(of: turns.count) {
                        if let last = turns.last { withAnimation { scroll.scrollTo(last.id) } }
                    }
                }
                Divider()
                HStack {
                    TextField("Ask Sim", text: $typed, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { send() }
                    Button {
                        send()
                    } label: {
                        Image(systemName: "arrow.up.circle.fill").font(.title2)
                    }
                    .disabled(typed.trimmingCharacters(in: .whitespaces).isEmpty || waiting)
                }
                .padding()
            }
            .navigationTitle("Ask")
        }
    }

    private func send() {
        let text = typed.trimmingCharacters(in: .whitespaces)
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
                turns.append(Turn(mine: false, text: said.isEmpty ? "(Sim had nothing to say)" : said))
            } catch {
                turns.append(Turn(mine: false, text: error.localizedDescription))
            }
        }
    }
}
