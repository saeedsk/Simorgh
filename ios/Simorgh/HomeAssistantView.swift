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
/// It reuses the `HOME_ASSISTANT_URL` the house already has. The app does
/// NOT carry a Home Assistant token: this is a browser, so it is HA's own
/// login and its own cookie, in a data store separate from everything else
/// the app does.
struct HomeAssistantView: View {
    @EnvironmentObject var store: Store
    @State private var address: String = UserDefaults.standard.string(forKey: "sim.haURL") ?? ""
    @State private var editing = false

    var body: some View {
        NavigationStack {
            Group {
                if let url = URL(string: address), !address.isEmpty, url.scheme != nil {
                    Web(url: url)
                        .ignoresSafeArea(edges: .bottom)
                } else {
                    setup
                }
            }
            .navigationTitle("Home Assistant")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { editing = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(isPresented: $editing) { editor }
        }
    }

    private var setup: some View {
        ContentUnavailableView {
            Label("Home Assistant", systemImage: "house.badge.wifi")
        } description: {
            Text("Point this at your Home Assistant and it opens here, logged in with its own session.")
        } actions: {
            Button("Set the address") { editing = true }.buttonStyle(.borderedProminent).tint(Brand.lapis)
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
                    Text("The same address you use in a browser. It is kept on this phone only.")
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
        // Its own cookie jar: signing in here must not touch anything else,
        // and signing out of it must not sign out of anything else.
        config.websiteDataStore = .default()
        config.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: config)
        view.allowsBackForwardNavigationGestures = true
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        if view.url == nil { view.load(URLRequest(url: url)) }
    }
}
