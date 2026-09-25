import Foundation
import Security

/// Where Sim is, and this device's own token.
///
/// The token goes in the KEYCHAIN, not UserDefaults: it can answer
/// Guardian's questions, which is the one capability worth protecting from
/// a backup or a file dump. It is per-device and revocable (`devices
/// revoke` on Sim), so the recovery from a lost phone is one line there
/// rather than a rotation here.
@MainActor
final class Store: ObservableObject {
    @Published var baseURL: String {
        didSet { UserDefaults.standard.set(baseURL, forKey: Keys.baseURL) }
    }
    @Published private(set) var token: String?
    @Published private(set) var deviceName: String?
    @Published private(set) var capabilities: [String] = []

    /// Every address Sim is known to answer on, best first. Sim reports
    /// these itself (`/api/addresses`, and in the pairing reply), and
    /// Bonjour adds whatever it finds on the LAN.
    ///
    /// It was ONE address, typed at pairing time, and it was a LAN address
    /// -- so the app stopped working the moment the creator left the house
    /// ("I turned on tailscale on both mac and iphone and went outside, sim
    /// app didn't work", 2026-09-25). Sim had been listening on the tailnet
    /// all along.
    @Published private(set) var candidates: [String] = []

    private enum Keys {
        static let baseURL = "sim.baseURL"
        static let candidates = "sim.candidates"
        static let name = "sim.deviceName"
        static let caps = "sim.capabilities"
        static let keychain = "sim.deviceToken"
    }

    init() {
        baseURL = UserDefaults.standard.string(forKey: Keys.baseURL) ?? "http://192.168.50.33:8765"
        deviceName = UserDefaults.standard.string(forKey: Keys.name)
        capabilities = UserDefaults.standard.stringArray(forKey: Keys.caps) ?? []
        token = Self.readKeychain(Keys.keychain)
        candidates = UserDefaults.standard.stringArray(forKey: Keys.candidates) ?? []
        if candidates.isEmpty && !baseURL.isEmpty { candidates = [baseURL] }
    }

    /// Learn addresses without forgetting the working one. Sim's own order
    /// is kept (it puts the tailnet first, which reaches Sim both at home
    /// and away) except that whatever is working NOW stays first.
    func adopt(_ addresses: [String]) {
        var merged = candidates
        for address in addresses {
            let clean = address.trimmingCharacters(in: .whitespaces).trimmingSuffix("/")
            if !clean.isEmpty && !merged.contains(clean) { merged.append(clean) }
        }
        candidates = merged
        UserDefaults.standard.set(merged, forKey: Keys.candidates)
    }

    /// This one answered; try it first from now on.
    func working(_ address: String) {
        let clean = address.trimmingCharacters(in: .whitespaces).trimmingSuffix("/")
        guard !clean.isEmpty else { return }
        if baseURL != clean { baseURL = clean }
        var rest = candidates.filter { $0 != clean }
        rest.insert(clean, at: 0)
        candidates = rest
        UserDefaults.standard.set(rest, forKey: Keys.candidates)
    }

    var paired: Bool { token != nil }

    /// Whether Sim granted this device a capability. Advisory only: the
    /// server refuses on its own authority whatever this thinks, so this
    /// exists to hide a button, never to permit one.
    func may(_ capability: String) -> Bool { capabilities.contains(capability) }

    func save(token: String, name: String, capabilities: [String]) {
        Self.writeKeychain(Keys.keychain, value: token)
        UserDefaults.standard.set(name, forKey: Keys.name)
        UserDefaults.standard.set(capabilities, forKey: Keys.caps)
        self.token = token
        self.deviceName = name
        self.capabilities = capabilities
    }

    /// Forget this device's token locally. It does NOT revoke it on Sim --
    /// say so wherever this is offered, because a person who thinks they
    /// have revoked a lost phone and has not is worse off than one who
    /// knows they must.
    func forget() {
        Self.deleteKeychain(Keys.keychain)
        UserDefaults.standard.removeObject(forKey: Keys.name)
        UserDefaults.standard.removeObject(forKey: Keys.caps)
        token = nil
        deviceName = nil
        capabilities = []
    }

    // MARK: - Keychain

    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "house.simorgh.app",
         kSecAttrAccount as String: account]
    }

    private static func readKeychain(_ account: String) -> String? {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data, let text = String(data: data, encoding: .utf8)
        else { return nil }
        return text
    }

    private static func writeKeychain(_ account: String, value: String) {
        deleteKeychain(account)
        var q = query(account)
        q[kSecValueData as String] = Data(value.utf8)
        // Not in an iCloud backup, and only readable while the phone is
        // unlocked: a token that can approve should not travel.
        q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }

    private static func deleteKeychain(_ account: String) {
        SecItemDelete(query(account) as CFDictionary)
    }
}

extension String {
    /// `trimmingSuffix("/")` rather than `hasSuffix` twice at every call
    /// site: a trailing slash is the difference between a working address
    /// and a double-slashed 404.
    func trimmingSuffix(_ suffix: String) -> String {
        var out = self
        while out.hasSuffix(suffix) { out.removeLast(suffix.count) }
        return out
    }
}
