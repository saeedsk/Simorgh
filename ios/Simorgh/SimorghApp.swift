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

/// Ask, Home, House, Cameras, Console, Settings. Home arrived with stage 12
/// item 3a (`POST /api/action`); until that route existed a control tab
/// would have been a button that lies.
struct RootView: View {
    var body: some View {
        TabView {
            AskView()
                .tabItem { Label("Ask", systemImage: "bubble.left.and.bubble.right") }
            HomeView()
                .tabItem { Label("Home", systemImage: "lightbulb") }
            HouseView()
                .tabItem { Label("House", systemImage: "house") }
            ConsoleView()
                .tabItem { Label("Console", systemImage: "terminal") }
            CamerasView()
                .tabItem { Label("Cameras", systemImage: "video") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}
