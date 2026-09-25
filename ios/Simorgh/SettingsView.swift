import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var store: Store
    @State private var reachable: String?
    @State private var haURL = UserDefaults.standard.string(forKey: "sim.haURL") ?? ""
    @State private var haFromSim: String?

    var body: some View {
        NavigationStack {
            List {
                Section("This device") {
                    LabeledContent("Name", value: store.deviceName ?? "not paired")
                    LabeledContent("May") {
                        Text(store.capabilities.isEmpty ? "—" : store.capabilities.joined(separator: ", "))
                    }
                }
                Section("Sim") {
                    LabeledContent("Address") {
                        TextField("http://…", text: $store.baseURL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .multilineTextAlignment(.trailing)
                    }
                    Button("Check") { Task { await check() } }
                    Button("Find Sim") { Task { await find() } }
                    if let reachable { Text(reachable).font(.footnote).foregroundStyle(.secondary) }
                    if store.candidates.count > 1 {
                        // Worth showing: "which of these is it using" is the
                        // first question when the app works at home and not
                        // outside it.
                        ForEach(store.candidates, id: \.self) { address in
                            HStack {
                                Image(systemName: address == store.baseURL
                                      ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(address == store.baseURL ? Brand.gold : Color.secondary)
                                Text(address).font(.caption2).foregroundStyle(.secondary)
                                    .lineLimit(1).truncationMode(.middle)
                            }
                        }
                    }
                }
                // `Section(_ title:)` has no `footer:` overload; a header
                // closure does.
                Section {
                    LabeledContent("Address") {
                        TextField("from Sim", text: haOverride)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .multilineTextAlignment(.trailing)
                    }
                    Button("Use Sim's address") {
                        UserDefaults.standard.removeObject(forKey: "sim.haURL")
                        haURL = ""
                        Task { await fromSim() }
                    }
                    if let said = haFromSim {
                        Text(said).font(.footnote).foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Home Assistant")
                } footer: {
                    // Where this belongs: the Home tab is the house itself
                    // now, and an address field on top of it was chrome in
                    // the way (the creator, 2026-09-25).
                    Text("Sim supplies this from HOME_ASSISTANT_URL. Leave it empty to use Sim's.")
                }
                Section {
                    Button("Forget this pairing", role: .destructive) { store.forget() }
                } footer: {
                    // The distinction matters: somebody who believes a lost
                    // phone is revoked and is wrong is worse off than
                    // somebody who knows they must go and revoke it.
                    Text("This only forgets the token here. To stop it working at all, run  devices revoke  on Sim.")
                }
            }
            .navigationTitle("Settings")
            .task { await fromSim() }
        }
    }

    /// Writes through as it is typed, so there is no Done button to forget.
    /// Empty means "use whatever Sim says", which is the default and the
    /// thing that should need no action at all.
    private var haOverride: Binding<String> {
        Binding(get: { haURL }, set: { typed in
            haURL = typed
            let clean = typed.trimmingCharacters(in: .whitespaces)
            if clean.isEmpty { UserDefaults.standard.removeObject(forKey: "sim.haURL") }
            else { UserDefaults.standard.set(clean, forKey: "sim.haURL") }
        })
    }

    private func fromSim() async {
        do {
            let found = try await Api(baseURL: store.baseURL, token: store.token).homeAssistant()
            let url = (found.url ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            haFromSim = url.isEmpty ? (found.detail ?? "Sim does not know.") : "Sim says \(url)"
        } catch {
            haFromSim = nil
        }
    }

    /// Bonjour on this network, then race everything Sim has ever said it
    /// answers on.
    private func find() async {
        reachable = "looking…"
        if let found = await Finding.settle(store) {
            reachable = "using \(found)"
        } else {
            reachable = "no Sim answered on any known address"
        }
    }

    private func check() async {
        do {
            let status = try await Api(baseURL: store.baseURL, token: store.token).status()
            reachable = "reached Sim — \(status.state ?? "running")"
        } catch {
            reachable = error.localizedDescription
        }
    }
}
