import SwiftUI

/// Sim's console: a tail of a ledger stream.
///
/// "Structured logs are Ledger events" -- so there is no separate log file
/// to read, and `system` is the stream that reads as a console. Every other
/// stream is reachable by name, which is what makes this more useful than
/// a log viewer: `task:<id>` is one turn's whole story, and that is where
/// the answer usually is.
struct ConsoleView: View {
    @EnvironmentObject var store: Store
    @State private var events: [Api.LogEvent] = []
    @State private var streams: [String] = []
    @State private var stream = "system"
    @State private var problem: String?
    @State private var following = true

    private var api: Api { Api(baseURL: store.baseURL, token: store.token) }

    var body: some View {
        NavigationStack {
            ScrollViewReader { scroll in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if events.isEmpty {
                            Text(problem ?? "Nothing on this stream yet.")
                                .font(.footnote)
                                .foregroundStyle(problem == nil ? Color.secondary : Color.red)
                                .padding()
                        }
                        ForEach(events) { event in
                            row(event).id(event.id)
                        }
                    }
                    .padding(.vertical, 8)
                }
                .onChange(of: events.count) {
                    guard following, let last = events.last else { return }
                    withAnimation { scroll.scrollTo(last.id, anchor: .bottom) }
                }
            }
            .background(Color(.systemBackground))
            .navigationTitle("Console")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        // `system` first, then whatever Sim has. A picker
                        // that has to be typed into is a picker nobody uses
                        // on a phone.
                        Button("system") { stream = "system"; Task { await load() } }
                        ForEach(streams.filter { $0 != "system" }, id: \.self) { name in
                            Button(name) { stream = name; Task { await load() } }
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Text(stream).lineLimit(1)
                            Image(systemName: "chevron.down").font(.caption2)
                        }
                        .font(.subheadline)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        following.toggle()
                    } label: {
                        Image(systemName: following ? "arrow.down.to.line.compact" : "pause")
                    }
                    .tint(following ? .accentColor : .secondary)
                }
            }
            .refreshable { await load() }
            .task { await first() }
            .task { await poll() }
        }
    }

    private func row(_ event: Api.LogEvent) -> some View {
        HStack(alignment: .top, spacing: 8) {
            if let ts = event.ts, ts > 0 {
                Text(Date(timeIntervalSince1970: ts), format: .dateTime.hour().minute().second())
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(event.type ?? "")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(Self.tint(event.type))
                let said = event.summary
                if !said.isEmpty {
                    Text(said).font(.footnote).textSelection(.enabled)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 5)
    }

    /// Colour by what the event IS, not by a level: the ledger has no
    /// levels, and inventing one would be a guess drawn as a fact.
    private static func tint(_ type: String?) -> Color {
        guard let type else { return .secondary }
        if type.contains("failed") || type.contains("denied") || type.contains("error") { return Brand.crimson }
        if type.contains("blocked") || type.contains("needs_human") { return Brand.gold }
        if type.contains("completed") { return Brand.emerald }
        return .secondary
    }

    private func first() async {
        streams = (try? await api.streams()) ?? []
        await load()
    }

    private func load() async {
        do {
            // Oldest first, so it reads downward like a console and the
            // newest line is the one at the bottom.
            events = try await api.logs(stream: stream, limit: 200)
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(4))
            if Task.isCancelled { return }
            if following { await load() }
        }
    }
}
