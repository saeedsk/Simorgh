import SwiftUI
import WebKit

/// Home Assistant's own interface, inside the app.
///
/// Sim's Home tab is the useful daily surface -- tiles, one tap, Sim's own
/// view of the house. This is the full thing for everything that surface
/// does not reach: automations, the history graphs, add-ons, the editors.
/// Wrapping a web view rather than rebuilding any of it is the honest
/// trade; Home Assistant's UI is thousands of screens and this app should
/// not pretend to be a second one.
///
/// The address comes from SIM (`GET /api/house/assistant`), not from the
/// person. This screen used to say in its own comment that it "reuses the
/// HOME_ASSISTANT_URL the house already has" while in fact presenting an
/// empty text field -- the creator, 2026-09-25: "in the home tab,
/// automatically make ha available to me (don't like the idea that i have
/// to manually enter ha address)". Sim had the right address in
/// `secrets.toml` the whole time, because that is what its own `home_*`
/// tools call.
///
/// The app carries no Home Assistant token: this is a browser, so it is
/// HA's own login and its own cookie, in a data store separate from
/// everything else the app does.
struct HomeAssistantView: View {
    @EnvironmentObject var store: Store
    /// What Sim said, remembered so a later launch opens straight into the
    /// house rather than waiting on a round trip.
    @State private var address = UserDefaults.standard.string(forKey: "sim.haURL") ?? ""
    @State private var asking = true
    @State private var problem: String?
    @State private var editing = false

    var body: some View {
        Group {
            if let url = URL(string: address), !address.isEmpty, url.scheme != nil {
                // FULL SCREEN, and no navigation bar: Home Assistant draws
                // its own header and sidebar, so a title bar above it is a
                // second one saying less. Only the tab bar remains, because
                // that is how you leave.
                Web(url: url)
                    .ignoresSafeArea(edges: .bottom)
            } else if asking {
                ProgressView("Finding Home Assistant…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color(.systemGroupedBackground))
            } else {
                // Chrome only when there is something to fix. The address
                // otherwise lives in Settings (House › gear), not on top of
                // the house.
                NavigationStack { unavailable.navigationTitle("Home Assistant") }
            }
        }
        .sheet(isPresented: $editing) { editor }
        .task { await find() }
    }

    /// Ask Sim. An address already remembered is still refreshed, quietly,
    /// so moving Home Assistant does not leave the phone pointing at the
    /// old place for ever.
    private func find() async {
        defer { asking = false }
        do {
            let found = try await Api(baseURL: store.baseURL, token: store.token).homeAssistant()
            let url = (found.url ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !url.isEmpty {
                address = url
                UserDefaults.standard.set(url, forKey: "sim.haURL")
                problem = nil
            } else {
                problem = found.detail ?? "Sim does not know where Home Assistant is."
            }
        } catch {
            // A remembered address still works offline from Sim; only say
            // something when there is nothing to show.
            if address.isEmpty { problem = (error as? Api.Failure)?.detail ?? error.localizedDescription }
        }
    }

    /// Only when Sim could not say and nothing was remembered. The manual
    /// field survives as a way out, not as the way in.
    private var unavailable: some View {
        ContentUnavailableView {
            Label("Home Assistant", systemImage: "house.badge.wifi")
        } description: {
            Text(problem ?? "Sim has not been told where Home Assistant is.")
        } actions: {
            Button("Try again") { asking = true; Task { await find() } }
                .buttonStyle(.borderedProminent).tint(Brand.lapis)
            Button("Enter the address") { editing = true }
        }
    }

    private var editor: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://homeassistant.local:8123", text: $address)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                } footer: {
                    Text("Sim normally supplies this from HOME_ASSISTANT_URL. "
                         + "Anything set here overrides it, on this phone only.")
                }
                Section {
                    Button("Use Sim's address") {
                        editing = false
                        asking = true
                        UserDefaults.standard.removeObject(forKey: "sim.haURL")
                        address = ""
                        Task { await find() }
                    }
                }
            }
            .navigationTitle("Home Assistant")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        UserDefaults.standard.set(address, forKey: "sim.haURL")
                        editing = false
                    }
                }
            }
        }
    }
}

private struct Web: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        // `.default()` and NOT `.nonPersistent()`: Home Assistant's "keep me
        // logged in" is a refresh token in local storage, and a
        // non-persistent store would throw it away at every launch and ask
        // for the password again for ever. Its own jar all the same --
        // signing in here touches nothing else the app does.
        config.websiteDataStore = .default()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        let view = WKWebView(frame: .zero, configuration: config)
        view.allowsBackForwardNavigationGestures = true
        // The panel is a full-bleed app; a bounce reveals a white band under
        // it that looks like a rendering fault.
        view.scrollView.bounces = false
        view.load(URLRequest(url: url))
        return view
    }

    /// Only ever loads when there is nothing loaded. Reloading on every
    /// SwiftUI update would throw away where somebody had navigated to --
    /// and, on Home Assistant, the dialog they were part way through.
    func updateUIView(_ view: WKWebView, context: Context) {
        if view.url == nil { view.load(URLRequest(url: url)) }
    }
}
