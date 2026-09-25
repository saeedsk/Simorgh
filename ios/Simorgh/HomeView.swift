import SwiftUI

/// The house: what is on, and one tap to change it.
///
/// Every tap is `home_call`, which goes through `POST /api/action` and
/// therefore through Guardian, exactly as the same request from a spoken
/// turn does. The phone gains no privilege the voice channel has not
/// already got.
///
/// The state shown is Sim's, not a guess: after a call it asks again
/// rather than assuming the light obeyed. `home_call`'s own description
/// says it "reports what actually changed, which is not always what was
/// asked for", and a tile that lies about a lamp is worse than a slow one.
struct HomeView: View {
    @EnvironmentObject var store: Store
    @State private var entities: [Api.Entity] = []
    @State private var problem: String?
    @State private var busy: Set<String> = []
    @State private var loading = true
    @State private var showingHA = false

    private var api: Api { Api(baseURL: store.baseURL, token: store.token) }
    private let columns = [GridItem(.adaptive(minimum: 160), spacing: 12)]

    var body: some View {
        NavigationStack {
            ScrollView {
                if !store.may("control") { needsControl }
                if let problem { failure(problem) }
                if loading && entities.isEmpty {
                    ProgressView().padding(.top, 60)
                } else if entities.isEmpty && problem == nil {
                    ContentUnavailableView("Nothing in the house",
                                           systemImage: "lightbulb.slash",
                                           description: Text("Sim found no devices. Is Home Assistant set up?"))
                        .padding(.top, 50)
                }
                ForEach(Self.groups, id: \.title) { group in
                    let rows = entities.filter { group.domains.contains($0.domain ?? "") }
                    if !rows.isEmpty {
                        section(group.title, rows)
                    }
                }
                let rest = entities.filter { entity in
                    !Self.groups.contains { $0.domains.contains(entity.domain ?? "") }
                }
                if !rest.isEmpty { section("Everything else", rest) }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Home")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingHA = true } label: {
                        Image(systemName: "house.badge.wifi")
                    }
                    .tint(Brand.lapis)
                }
            }
            .sheet(isPresented: $showingHA) { HomeAssistantView() }
            .refreshable { await load() }
            .task { await load() }
        }
    }

    private struct Group { let title: String; let domains: Set<String> }
    private static let groups: [Group] = [
        Group(title: "Lights", domains: ["light"]),
        Group(title: "Switches", domains: ["switch", "input_boolean", "fan"]),
        Group(title: "Screens and sound", domains: ["media_player"]),
        Group(title: "Climate", domains: ["climate", "sensor", "binary_sensor"]),
        Group(title: "Doors", domains: ["lock", "cover", "siren"]),
    ]

    private func section(_ title: String, _ rows: [Api.Entity]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.footnote).bold().foregroundStyle(.secondary)
                .padding(.horizontal, 20).padding(.top, 8)
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(rows) { entity in tile(entity) }
            }
            .padding(.horizontal, 16)
        }
    }

    private func tile(_ entity: Api.Entity) -> some View {
        let live = entity.on
        let canTap = entity.switchable && entity.available && store.may("control")
        return Button {
            Task { await toggle(entity) }
        } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: Self.glyph(entity))
                        .font(.title3)
                        .foregroundStyle(live ? Brand.gold : Color.secondary)
                    Spacer()
                    if busy.contains(entity.entity_id) {
                        ProgressView().controlSize(.mini)
                    } else if entity.switchable {
                        Circle()
                            .fill(live ? Brand.emerald : Color.secondary.opacity(0.35))
                            .frame(width: 9, height: 9)
                    }
                }
                Text(entity.label).font(.subheadline.weight(.medium))
                    .lineLimit(2).multilineTextAlignment(.leading)
                Text(entity.available ? entity.reading : "unavailable")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(live ? Brand.gold.opacity(0.12) : Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(live ? Brand.gold.opacity(0.5) : Color.clear, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(!canTap)
        .opacity(entity.available ? 1 : 0.5)
    }

    private static func glyph(_ entity: Api.Entity) -> String {
        switch entity.domain {
        case "light": return entity.on ? "lightbulb.fill" : "lightbulb"
        case "switch", "input_boolean": return "power"
        case "fan": return "fan"
        case "media_player": return "tv"
        case "lock": return (entity.state ?? "") == "locked" ? "lock.fill" : "lock.open"
        case "cover": return "blinds.horizontal.closed"
        case "siren": return "bell.fill"
        case "climate": return "thermometer.medium"
        default: return "dot.circle"
        }
    }

    private func toggle(_ entity: Api.Entity) async {
        guard entity.switchable else { return }
        busy.insert(entity.entity_id)
        defer { busy.remove(entity.entity_id) }
        let domain = entity.domain ?? "homeassistant"
        let service = "\(domain).turn_\(entity.on ? "off" : "on")"
        do {
            _ = try await api.action("home_call", ["service": service, "target": entity.entity_id])
            // Ask, never assume: the light may not have obeyed.
            await load(quietly: true)
        } catch {
            problem = error.localizedDescription
        }
    }

    private func load(quietly: Bool = false) async {
        if !quietly { loading = true }
        defer { loading = false }
        do {
            entities = try await api.house()
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    private var needsControl: some View {
        Label("This phone may look, not touch. Pair it again  with control.",
              systemImage: "hand.raised")
            .font(.footnote)
            .card(tint: Brand.gold)
            .padding(.horizontal, 16).padding(.top, 12)
    }

    private func failure(_ said: String) -> some View {
        Text(said).font(.footnote).foregroundStyle(Brand.crimson)
            .frame(maxWidth: .infinity, alignment: .leading)
            .card(tint: Brand.crimson)
            .padding(.horizontal, 16).padding(.top, 12)
    }
}
