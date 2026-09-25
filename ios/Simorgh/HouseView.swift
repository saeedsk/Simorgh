import SwiftUI

/// What Sim is doing, and what it is waiting to be told.
///
/// The approvals are the reason this app exists. `ui.prompt` and
/// `ui.prompt.answered` have been on Sim's bus since Guardian could
/// escalate, and until stage 12 item 3 only the terminal published the
/// answer -- so every irreversible action waited for somebody at that desk.
/// They are drawn as a card rather than a list row because a question
/// holding up the house is not the same kind of thing as a log line.
struct HouseView: View {
    @EnvironmentObject var store: Store
    @State private var prompts: [Api.Prompt] = []
    @State private var activity: [Api.ActivityRow] = []
    @State private var problem: String?
    @State private var answering: String?
    @State private var reachable = true
    @State private var showingSettings = false

    private var api: Api { Api(baseURL: store.baseURL, token: store.token) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if !reachable { offline }
                    ForEach(prompts) { prompt in promptCard(prompt) }
                    if let problem, reachable {
                        Text(problem).font(.footnote).foregroundStyle(.red)
                            .padding(.horizontal, 16)
                    }
                    lately
                }
                .padding(.vertical, 12)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("House")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingSettings = true } label: { Image(systemName: "gearshape") }
                        .tint(.secondary)
                }
            }
            .sheet(isPresented: $showingSettings) { SettingsView() }
            .refreshable { await load() }
            .task { await load() }
            .task { await poll() }
        }
    }

    private var offline: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text("Can't reach Sim").font(.subheadline).bold()
                Text(problem ?? store.baseURL).font(.caption).foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: "wifi.exclamationmark").foregroundStyle(Brand.crimson)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .padding(.horizontal, 16)
    }

    private func promptCard(_ prompt: Api.Prompt) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "hand.raised.fill").foregroundStyle(Brand.gold)
                Text("Sim is waiting for you").font(.subheadline).bold()
                Spacer()
                if prompt.seconds_left > 0 {
                    Text("\(Int(prompt.seconds_left))s")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            // Sim's own words, unchanged: the point of answering from here
            // is that a person judges what Guardian escalated.
            Text(prompt.question).font(.callout)

            if store.may("approve") {
                HStack(spacing: 10) {
                    ForEach(prompt.options, id: \.self) { option in
                        Button {
                            Task { await answer(prompt, with: option) }
                        } label: {
                            Text(option).frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(Self.isNo(option) ? Color.secondary : Brand.lapis)
                        .disabled(answering != nil)
                    }
                }
            } else {
                Text("This phone may not answer. Pair it again with  approve.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .stroke(Brand.gold.opacity(0.45), lineWidth: 1))
        .padding(.horizontal, 16)
    }

    /// The refusing answer is grey, so the eye does not read "no" as the
    /// confident one. Guardian's options are its own words, so this
    /// recognises the usual ones rather than assuming a shape.
    private static func isNo(_ option: String) -> Bool {
        ["no", "deny", "cancel", "never", "stop"].contains(option.lowercased())
    }

    private var lately: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Lately").font(.footnote).bold().foregroundStyle(.secondary)
                .padding(.horizontal, 20)
            if activity.isEmpty {
                Text(reachable ? "Nothing yet." : "—")
                    .font(.footnote).foregroundStyle(.tertiary)
                    .padding(.horizontal, 20)
            }
            VStack(spacing: 0) {
                ForEach(Array(activity.prefix(40).enumerated()), id: \.element.id) { index, row in
                    if index > 0 { Divider().padding(.leading, 14) }
                    HStack(alignment: .top, spacing: 10) {
                        Circle().fill(.tertiary).frame(width: 6, height: 6).padding(.top, 6)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.line).font(.callout)
                            if let detail = row.detail {
                                Text(detail).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                        Spacer(minLength: 0)
                        if let ts = row.ts, ts > 0 {
                            Text(Date(timeIntervalSince1970: ts), style: .relative)
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                }
            }
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .padding(.horizontal, 16)
        }
    }

    private func answer(_ prompt: Api.Prompt, with option: String) async {
        answering = prompt.prompt_id
        defer { answering = nil }
        do {
            try await api.answer(prompt: prompt.prompt_id, with: option)
            withAnimation { prompts.removeAll { $0.prompt_id == prompt.prompt_id } }
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
            reachable = true
        } catch {
            problem = error.localizedDescription
            reachable = false
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
