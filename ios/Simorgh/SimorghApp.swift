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

/// Ask, Home, Cameras, House, Console.
///
/// **Home is Home Assistant itself**, full screen. It used to be Sim's own
/// tiles with a small Home Assistant button in the corner, which put the
/// thing people actually want one tap and one sheet away -- the creator,
/// 2026-09-25: "why showing ha icon on top of the page, let's cut the
/// intermediate action and show ha page directly in sim app home tab
/// (preferably in full screen)". HA's UI is the whole house; Sim's tiles
/// are a convenience over part of it, so the tiles are what moved (to
/// House), not the other way round.
struct RootView: View {
    var body: some View {
        // FIVE. iOS folds a sixth into a "More" list, and the two that
        // would end up there -- Sim's own controls and Settings -- are the
        // two nobody opens daily. They live one tap inside House instead,
        // where a person already is when they want them.
        TabView {
            AskView()
                .tabItem { Label("Ask", systemImage: "bubble.left.and.bubble.right") }
            HomeAssistantView()
                .tabItem { Label("Home", systemImage: "house.fill") }
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
