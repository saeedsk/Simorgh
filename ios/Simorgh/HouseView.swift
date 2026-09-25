import SwiftUI

/// What Sim is doing, and what it is waiting to be told.
///
/// The approvals section is the reason this app exists. `ui.prompt` and
/// `ui.prompt.answered` have been on Sim's bus since Guardian could
/// escalate, and until stage 12 item 3 only the terminal published the
/// answer -- so every irreversible action waited for somebody at that desk.
struct HouseView: View {
    @EnvironmentObject var store: Store
    @State private var prompts: [Api.Prompt] = []
    @State private var activity: [Api.ActivityRow] = []
    @State private var problem: String?
    @State private var answering: String?

    private var api: Api { Api(baseURL: store.baseURL, token: store.token) }

    var body: some View {
        NavigationStack {
            List {
                if !prompts.isEmpty {
                    Section("Sim is waiting for you") {
                        ForEach(prompts) { prompt in
                            promptRow(prompt)
                        }
                    }
                }
                if let problem {
                    Section { Text(problem).font(.footnote).foregroundStyle(.red) }
                }
                Section("Lately") {
                    if activity.isEmpty {
                        Text("nothing yet").foregroundStyle(.secondary)
                    }
                    ForEach(activity.prefix(40)) { row in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.text ?? "").font(.callout)
                            if let kind = row.kind {
                                Text(kind).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("House")
            .refreshable { await load() }
            .task { await load() }
            // Only while this tab is on screen: a phone in a pocket
            // refreshing five tabs is a battery complaint that reads as
            // "the app is broken".
            .task(id: "poll") { await poll() }
        }
    }

    @ViewBuilder private func promptRow(_ prompt: Api.Prompt) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            // Sim's own words, unchanged: the point of answering from here
            // is that a person judges what Guardian escalated.
            Text(prompt.question).font(.callout)
            if prompt.seconds_left > 0 {
                Text("\(Int(prompt.seconds_left))s left").font(.caption2).foregroundStyle(.secondary)
            }
            if store.may("approve") {
                HStack {
                    ForEach(prompt.options, id: \.self) { option in
                        Button(option) {
                            Task { await answer(prompt, with: option) }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(answering != nil)
                    }
                }
            } else {
                // Honest about why the buttons are missing, and how to fix
                // it, rather than a disabled row with no explanation.
                Text("This phone may not answer. Pair it again with approve.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func answer(_ prompt: Api.Prompt, with option: String) async {
        answering = prompt.prompt_id
        defer { answering = nil }
        do {
            try await api.answer(prompt: prompt.prompt_id, with: option)
            prompts.removeAll { $0.prompt_id == prompt.prompt_id }
        } catch let failure as Api.Failure where failure.tooLate {
            // Somebody at the terminal got there first, or it timed out.
            // Saying so beats a spinner that stops.
            problem = failure.detail
            await load()
        } catch {
            problem = error.localizedDescription
        }
    }

    private func load() async {
        do {
            prompts = try await api.prompts()
            activity = try await api.activity()
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(5))
            if Task.isCancelled { return }
            await load()
        }
    }
}
