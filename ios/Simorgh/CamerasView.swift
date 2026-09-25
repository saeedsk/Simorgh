import AVKit
import SwiftUI

/// The cameras: a still from each, and live video where a relay is running.
///
/// The two are different things on Sim and the tab says so. `cameras` are
/// stills refreshed as Sim takes them; `streams` are HLS relays that exist
/// only while something has started one -- so "no live view" here means
/// nothing is relaying, not that the camera is down. Asking Sim to START a
/// relay is `cam_stream`, which needs the action route (stage 12 item 3a);
/// until then this offers what exists rather than a button that fails.
struct CamerasView: View {
    @EnvironmentObject var store: Store
    @State private var stills: [Api.Feeds.Still] = []
    @State private var live: [Api.Feeds.Live] = []
    @State private var problem: String?
    @State private var watching: Api.Feeds.Live?
    @State private var refreshed = Date()

    private var api: Api { Api(baseURL: store.baseURL, token: store.token) }
    private let columns = [GridItem(.adaptive(minimum: 150), spacing: 12)]

    var body: some View {
        NavigationStack {
            ScrollView {
                if let problem {
                    Text(problem).font(.footnote).foregroundStyle(Brand.crimson)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .card(tint: Brand.crimson).padding(.horizontal, 16).padding(.top, 12)
                } else if stills.isEmpty {
                    ContentUnavailableView("No cameras", systemImage: "video.slash",
                                           description: Text("Sim has not taken a still yet."))
                        .padding(.top, 60)
                }
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(stills, id: \.name) { still in
                        tile(still)
                    }
                }
                .padding(16)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Cameras")
            .refreshable { await load() }
            .task { await load() }
            .task { await poll() }
            .sheet(item: $watching) { feed in
                LiveSheet(url: api.url(feed.url ?? ""), title: feed.name ?? "Camera")
            }
        }
    }

    private func tile(_ still: Api.Feeds.Still) -> some View {
        let feed = liveFor(still)
        return VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .topTrailing) {
                // `refreshed` in the id makes AsyncImage refetch rather
                // than show a cached still for ever.
                AsyncImage(url: api.url(still.url ?? "")) { phase in
                    switch phase {
                    case .success(let image): image.resizable().scaledToFill()
                    case .failure: Color(.secondarySystemBackground)
                            .overlay(Image(systemName: "photo").foregroundStyle(.tertiary))
                    default: Color(.secondarySystemBackground).overlay(ProgressView())
                    }
                }
                .id("\(still.name)-\(refreshed.timeIntervalSince1970)")
                .frame(height: 110)
                .clipped()

                if feed?.live == true {
                    Label("LIVE", systemImage: "dot.radiowaves.left.and.right")
                        .font(.caption2.bold())
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(Brand.crimson, in: Capsule())
                        .foregroundStyle(.white)
                        .padding(6)
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(still.name).font(.subheadline.weight(.medium)).lineLimit(1)
                Text(subtitle(still)).font(.caption2).foregroundStyle(.secondary)
            }
            .padding(10)
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { if let feed, feed.live == true { watching = feed } }
    }

    private func subtitle(_ still: Api.Feeds.Still) -> String {
        var bits: [String] = []
        if let kind = still.kind, !kind.isEmpty { bits.append(kind) }
        if let at = still.at, at > 0 {
            let ago = Date().timeIntervalSince1970 - at
            bits.append(ago < 90 ? "just now" : "\(Int(ago / 60)) min ago")
        }
        return bits.joined(separator: " · ")
    }

    /// A live relay for this camera, matched by name -- the only field the
    /// two lists share.
    private func liveFor(_ still: Api.Feeds.Still) -> Api.Feeds.Live? {
        live.first { ($0.name ?? "").caseInsensitiveCompare(still.name) == .orderedSame }
    }

    private func load() async {
        do {
            let feeds = try await api.feeds()
            stills = feeds.cameras ?? []
            live = feeds.streams ?? []
            refreshed = Date()
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(20))
            if Task.isCancelled { return }
            await load()
        }
    }
}

extension Api.Feeds.Live: Identifiable {
    public var id: Int { channel ?? 0 }
}

private struct LiveSheet: View {
    let url: URL?
    let title: String

    var body: some View {
        NavigationStack {
            Group {
                if let url {
                    VideoPlayer(player: AVPlayer(url: url))
                } else {
                    ContentUnavailableView("Not paired", systemImage: "lock",
                                           description: Text("A live stream needs this device's token."))
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .ignoresSafeArea(edges: .bottom)
        }
    }
}
