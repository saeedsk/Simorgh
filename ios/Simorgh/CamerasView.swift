import AVKit
import SwiftUI

/// The cameras. iOS plays HLS natively, and Sim already serves it at
/// `/tv/hls/<n>/index.m3u8` -- so this is the one place a phone is a better
/// client than the television, where in-page video came back blank on the
/// Cast receiver.
struct CamerasView: View {
    @EnvironmentObject var store: Store
    @State private var cameras: [Camera] = []
    @State private var problem: String?
    @State private var watching: Camera?

    struct Camera: Identifiable, Hashable {
        let id: String
        let name: String
    }

    var body: some View {
        NavigationStack {
            Group {
                if let problem {
                    ContentUnavailableView("No cameras", systemImage: "video.slash",
                                           description: Text(problem))
                } else if cameras.isEmpty {
                    ProgressView().task { await load() }
                } else {
                    List(cameras) { camera in
                        Button { watching = camera } label: {
                            HStack {
                                Image(systemName: "video")
                                Text(camera.name)
                                Spacer()
                                Image(systemName: "chevron.right").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Cameras")
            .refreshable { await load() }
            .sheet(item: $watching) { camera in
                LiveView(url: Api(baseURL: store.baseURL, token: store.token).hlsURL(camera: camera.id),
                         title: camera.name)
            }
        }
    }

    private func load() async {
        do {
            let rows = try await Self.fetchCameras(baseURL: store.baseURL, token: store.token)
            cameras = rows
            problem = rows.isEmpty ? "Sim reported no cameras with a ready stream." : nil
        } catch {
            problem = error.localizedDescription
        }
    }

    /// `/api/dash/streams` is the dashboard's own list of cameras with a
    /// stream ready. Parsed loosely on purpose: it is a page's payload, not
    /// a contract, and a shape change should cost a camera rather than the
    /// whole tab.
    static func fetchCameras(baseURL: String, token: String?) async throws -> [Camera] {
        guard let url = URL(string: baseURL + "/api/dash/streams") else { return [] }
        var request = URLRequest(url: url, timeoutInterval: 15)
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, _) = try await URLSession.shared.data(for: request)
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [] }
        let rows = (root["streams"] as? [[String: Any]]) ?? (root["cameras"] as? [[String: Any]]) ?? []
        return rows.compactMap { row in
            let id = (row["channel"] as? Int).map(String.init)
                ?? (row["id"] as? String)
                ?? (row["channel"] as? String)
            guard let id else { return nil }
            return Camera(id: id, name: (row["name"] as? String) ?? "camera \(id)")
        }
    }
}

private struct LiveView: View {
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
            .ignoresSafeArea(edges: .bottom)
        }
    }
}
