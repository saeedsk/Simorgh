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
        // FIVE. iOS folds a sixth into a "More" list, and the two that
        // would end up there -- Home Assistant and Settings -- are the two
        // nobody opens daily. They live one tap inside Home and House
        // instead, where a person already is when they want them.
        TabView {
            AskView()
                .tabItem { Label("Ask", systemImage: "bubble.left.and.bubble.right") }
            HomeView()
                .tabItem { Label("Home", systemImage: "lightbulb") }
            CamerasView()
                .tabItem { Label("Cameras", systemImage: "video") }
            HouseView()
                .tabItem { Label("House", systemImage: "house") }
            ConsoleView()
                .tabItem { Label("Console", systemImage: "terminal") }
        }
        .tint(Brand.gold)
    }
}
