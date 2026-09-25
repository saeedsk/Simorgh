import SwiftUI

/// Sim's terminal, mirrored.
///
/// Not a log viewer and not the activity feed: the lines Sim actually
/// PRINTED, glyphs and all -- the same `⏺ 💬 chat`, `⎿ ✅ completed in
/// 3.2s`, `🎤 listening…` that are on the screen at home. `contracts/
/// console.py` has been capturing them all along so `console_tail` could
/// answer a question about Sim's own output; `GET /api/console` serves
/// them.
///
/// And a prompt, because a console you cannot type into is a window.
/// `POST /api/command` runs the line through `_handle_line` -- the
/// keyboard's own path -- so Guardian gates whatever it starts exactly as
/// it does at the terminal. It answers COMMANDS only; a line that parses
/// as chat is refused and pointed at the Ask tab, which is the right
/// answer rather than a second quiet way to talk to Sim.
struct ConsoleView: View {
    @EnvironmentObject var store: Store
    @State private var lines: [String] = []
    @State private var typed = ""
    @State private var problem: String?
    @State private var following = true
    @State private var running = false
    @State private var filter = ""
    @FocusState private var writing: Bool

    private var api: Api { Api(baseURL: store.baseURL, token: store.token) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                screen
                Divider()
                prompt
            }
            .background(Brand.night)
            .navigationTitle("Console")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { following.toggle() } label: {
                        Image(systemName: following ? "arrow.down.to.line.compact" : "pause.fill")
                    }
                    .tint(following ? Brand.gold : .secondary)
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { writing = false }
                }
            }
            .searchable(text: $filter, prompt: "filter")
            .onChange(of: filter) { Task { await load() } }
            .task { await load() }
            .task { await poll() }
        }
    }

    private var screen: some View {
        ScrollViewReader { scroll in
            ScrollView([.vertical, .horizontal]) {
                VStack(alignment: .leading, spacing: 1) {
                    if lines.isEmpty {
                        Text(problem ?? "Sim has not printed anything yet.")
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundStyle(problem == nil ? Color.secondary : Brand.crimson)
                            .padding()
                    }
                    ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                        // Monospaced and UNWRAPPED, inside a horizontal
                        // scroll: the tree's rails only line up if a long
                        // line stays one line.
                        Text(line)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(Self.tint(line))
                            .textSelection(.enabled)
                            .fixedSize(horizontal: true, vertical: false)
                            .id(index)
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: lines.count) {
                guard following, !lines.isEmpty else { return }
                withAnimation { scroll.scrollTo(lines.count - 1, anchor: .bottom) }
            }
        }
    }

    /// Sim's own colours, by the glyph it already prints. Nothing is
    /// invented: a line with no marker stays plain, because guessing a
    /// level the console does not have would be a colour that lies.
    private static func tint(_ line: String) -> Color {
        if line.contains("❌") || line.contains("[error]") { return Brand.crimson }
        if line.contains("⏸") || line.contains("[warn") { return Brand.gold }
        if line.contains("✅") { return Brand.emerald }
        if line.contains("⏺") || line.contains("❯") { return Brand.goldLight }
        if line.contains("🔊") || line.contains("🎤") { return Brand.amethyst }
        if line.contains("[info]") || line.contains("⎿") { return Color(white: 0.62) }
        return Color(white: 0.80)
    }

    private var prompt: some View {
        HStack(spacing: 8) {
            Text("❯").font(.system(size: 15, design: .monospaced)).foregroundStyle(Brand.gold)
            TextField("", text: $typed, prompt: Text("status, voice on, restart…")
                .foregroundColor(.gray))
                .font(.system(size: 14, design: .monospaced))
                .foregroundStyle(.white)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($writing)
                .submitLabel(.go)
                .onSubmit { run() }
            if running { ProgressView().controlSize(.small).tint(.white) }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color(white: 0.10))
    }

    private func run() {
        let line = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !line.isEmpty, !running else { return }
        typed = ""
        running = true
        Task {
            defer { running = false }
            do {
                _ = try await api.command(line)
            } catch {
                problem = error.localizedDescription
            }
            // Whatever it printed is on Sim's console, which is what this
            // screen already shows -- so there is nothing to render here
            // beyond asking again.
            await load()
        }
    }

    private func load() async {
        do {
            lines = try await api.console(limit: 400, contains: filter)
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(3))
            if Task.isCancelled { return }
            if following { await load() }
        }
    }
}
