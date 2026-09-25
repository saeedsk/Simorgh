import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var store: Store
    @State private var reachable: String?

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
                    if let reachable { Text(reachable).font(.footnote).foregroundStyle(.secondary) }
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
