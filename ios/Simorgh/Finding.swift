import Foundation
import Network

/// Finding Sim, without being told where it is.
///
/// Two mechanisms, because they cover different places and neither covers
/// both:
///
///  - **Bonjour** (`_simorgh._tcp`) finds Sim on the same network with no
///    configuration at all, and keeps finding it when the router hands out
///    a different address. It does NOT cross a tailnet: mDNS is multicast
///    and multicast is not routed, so away from home this finds nothing.
///  - **Remembered addresses**, which Sim reports itself (`/api/addresses`
///    and the pairing reply) with the tailnet first. That is what works at
///    the coffee shop.
///
/// So: browse, merge, then RACE. Whichever address answers `/api/status`
/// first wins and is remembered as first-to-try. The creator, 2026-09-25:
/// "I turned on tailscale on both mac and iphone and went outside, sim app
/// didn't work" -- it had one hard-coded LAN address and no way to learn a
/// second.
enum Finding {
    /// The Bonjour service Sim advertises.
    static let service = "_simorgh._tcp"

    /// Base URLs found on the local network. Returns early once something
    /// is found; gives up after `seconds` so a network with no Sim on it
    /// does not hold the app open.
    static func onThisNetwork(seconds: Double = 2.0) async -> [String] {
        await withCheckedContinuation { go in
            let browser = NWBrowser(for: .bonjourWithTXTRecord(type: service, domain: nil),
                                    using: .tcp)
            var answered = false
            let finish: ([String]) -> Void = { found in
                guard !answered else { return }
                answered = true
                browser.cancel()
                go.resume(returning: found)
            }
            browser.browseResultsChangedHandler = { results, _ in
                var urls: [String] = []
                for result in results {
                    // The TXT record carries the address Sim itself
                    // considers best, so a discovered Sim hands over its
                    // tailnet name too -- one browse, both places.
                    if case let .bonjour(txt) = result.metadata {
                        if let best = txt["base"], !best.isEmpty { urls.append(best) }
                        if let all = txt["addresses"] {
                            // `dns-sd` escapes the separators it prints as
                            // `\ `; strip any backslash before splitting so
                            // an address never arrives with one glued on.
                            urls.append(contentsOf: all
                                .replacingOccurrences(of: "\\", with: "")
                                .split(whereSeparator: { $0 == " " || $0 == "," })
                                .map(String.init)
                                .filter { $0.hasPrefix("http") })
                        }
                    }
                }
                if !urls.isEmpty { finish(urls) }
            }
            browser.stateUpdateHandler = { state in
                if case .failed = state { finish([]) }
            }
            browser.start(queue: .global(qos: .userInitiated))
            Task {
                try? await Task.sleep(for: .seconds(seconds))
                finish([])
            }
        }
    }

    /// The first of `addresses` that answers, or nil. Probed CONCURRENTLY:
    /// tried one after another, a phone away from home would sit through a
    /// timeout per LAN address before reaching the one that works.
    static func firstThatAnswers(_ addresses: [String], token: String?,
                                 each seconds: Double = 3.0) async -> String? {
        let tried = Array(NSOrderedSet(array: addresses).array as? [String] ?? addresses)
        guard !tried.isEmpty else { return nil }
        return await withTaskGroup(of: (Int, String)?.self) { group in
            for (rank, address) in tried.enumerated() {
                group.addTask {
                    await answers(address, token: token, seconds: seconds) ? (rank, address) : nil
                }
            }
            // The BEST that answers, not merely the quickest: Sim's own
            // order puts the tailnet first because it works in both
            // places, and a LAN address that wins a race by 10 ms would
            // otherwise be adopted and then break at the front door.
            var best: (Int, String)?
            for await found in group {
                guard let found else { continue }
                if best == nil || found.0 < best!.0 { best = found }
            }
            return best?.1
        }
    }

    private static func answers(_ address: String, token: String?, seconds: Double) async -> Bool {
        guard let url = URL(string: address.trimmingSuffix("/") + "/api/status") else { return false }
        var request = URLRequest(url: url, timeoutInterval: seconds)
        request.httpMethod = "GET"
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            // `/api/status` is open, so even an unpaired app gets 200 here;
            // anything that answers at all is a Sim.
            return (200..<500).contains(status)
        } catch {
            return false
        }
    }

    /// Bonjour, plus what Sim told us last time, plus what it says now.
    /// Updates the store and returns the address in use.
    @MainActor
    static func settle(_ store: Store) async -> String? {
        store.adopt(await onThisNetwork())
        guard let working = await firstThatAnswers(store.candidates.isEmpty ? [store.baseURL] : store.candidates,
                                                   token: store.token) else { return nil }
        store.working(working)
        // Now ask Sim where else it can be reached, so the NEXT trip out
        // of the house already knows.
        if store.token != nil {
            if let said = try? await Api(baseURL: working, token: store.token).addresses() {
                store.adopt(said)
                store.working(working)          // keep the one that works first
            }
        }
        return working
    }
}
