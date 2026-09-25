import SwiftUI

@main
struct SimorghApp: App {
    @StateObject private var store = Store()

    var body: some Scene {
        WindowGroup {
            if store.paired {
                RootView()
                    .environmentObject(store)
            } else {
                PairingView()
                    .environmentObject(store)
            }
        }
    }
}

/// Four tabs today. Home (lights, scenes, thermostats) arrives with stage
/// 12 item 3a, `POST /api/action` -- a tab with nothing to call would be a
/// button that lies.
struct RootView: View {
    var body: some View {
        TabView {
            AskView()
                .tabItem { Label("Ask", systemImage: "bubble.left.and.bubble.right") }
            HouseView()
                .tabItem { Label("House", systemImage: "house") }
            CamerasView()
                .tabItem { Label("Cameras", systemImage: "video") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}
