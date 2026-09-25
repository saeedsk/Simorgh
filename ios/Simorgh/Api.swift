import Foundation

/// Every call to Sim, in one place.
///
/// The app renders and asks; Sim decides. There is no logic here about
/// what may be approved or which tools exist -- the server refuses on its
/// own authority, so the two cannot drift into disagreeing about what is
/// permitted.
struct Api {
    let baseURL: String
    let token: String?

    struct Failure: LocalizedError {
        let status: Int
        let detail: String
        var errorDescription: String? { detail }
        /// Sim said the request was fine but this device may not do it.
        var needsCapability: Bool { status == 403 }
        /// The question was already answered, or the moment has passed.
        var tooLate: Bool { status == 409 }
    }

    // MARK: - Shapes

    struct Prompt: Identifiable, Decodable, Equatable {
        let prompt_id: String
        let question: String
        let options: [String]
        let seconds_left: Double
        var id: String { prompt_id }
    }

    struct Status: Decodable {
        let state: String?
        let uptime_s: Double?
    }

    struct Paired: Decodable {
        let token: String
        let device_id: String
        let name: String
        let capabilities: [String]
    }

    struct ChatReply: Decodable {
        let text: String?
        let session_id: String?
    }

    struct ActivityRow: Identifiable, Decodable {
        let ts: Double?
        let kind: String?
        let text: String?
        var id: String { "\(ts ?? 0)-\(text ?? "")" }
    }

    // MARK: - Calls

    /// Pairing is the one call with no token: it SPENDS a code Sim minted
    /// locally and cannot create one.
    func pair(code: String) async throws -> Paired {
        try await send("/api/pair", method: "POST", body: ["code": code], authed: false)
    }

    func status() async throws -> Status { try await send("/api/status", method: "GET") }

    func prompts() async throws -> [Prompt] {
        struct Wrapper: Decodable { let prompts: [Prompt] }
        let wrapped: Wrapper = try await send("/api/prompts", method: "GET")
        return wrapped.prompts
    }

    func answer(prompt: String, with answer: String) async throws {
        struct Ok: Decodable { let ok: Bool? }
        let _: Ok = try await send("/api/prompts/\(prompt)", method: "POST", body: ["answer": answer])
    }

    func chat(_ text: String, session: String) async throws -> ChatReply {
        try await send("/api/chat", method: "POST", body: ["text": text, "session_id": session],
                       timeout: 180)
    }

    func activity() async throws -> [ActivityRow] {
        struct Wrapper: Decodable { let activity: [ActivityRow]? }
        let wrapped: Wrapper = try await send("/api/activity", method: "GET")
        return wrapped.activity ?? []
    }

    /// A camera's live HLS stream, for AVPlayer. The token rides in the
    /// query because a player cannot set a header.
    func hlsURL(camera: String) -> URL? {
        guard let token else { return nil }
        return URL(string: "\(baseURL)/tv/hls/\(camera)/index.m3u8?token=\(token)")
    }

    // MARK: - Transport

    private func send<T: Decodable>(_ path: String, method: String,
                                    body: [String: Any]? = nil,
                                    authed: Bool = true,
                                    timeout: TimeInterval = 20) async throws -> T {
        guard let url = URL(string: baseURL + path) else {
            throw Failure(status: 0, detail: "that is not a usable address for Sim")
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        if authed, let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            // Said plainly, because "could not connect" with no address is
            // the least useful thing an app can say.
            throw Failure(status: 0, detail: "could not reach Sim at \(baseURL) -- \(error.localizedDescription)")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw Failure(status: status, detail: Self.reason(from: data) ?? "Sim answered \(status)")
        }
        if T.self == Empty.self, let empty = Empty() as? T { return empty }
        return try JSONDecoder().decode(T.self, from: data)
    }

    struct Empty: Decodable {}

    /// Sim's errors are `{"error": {"code": ..., "detail": ...}}`. The
    /// detail is written for a person, so show it rather than a status.
    private static func reason(from data: Data) -> String? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let error = root["error"] as? [String: Any] {
            return (error["detail"] as? String) ?? (error["code"] as? String)
        }
        return root["error"] as? String
    }
}
