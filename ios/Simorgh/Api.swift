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

    /// One line of `/api/activity`. The server's key is `events`, not
    /// `activity` -- decoding the wrong one returned an empty list forever
    /// and the House tab looked idle while Sim worked (found 2026-09-25 by
    /// reading `httpapi.py:1149` rather than the screen).
    struct ActivityRow: Identifiable, Decodable {
        let ts: Double?
        let type: String?
        let summary: String?
        let tool: String?
        let ok: Bool?
        let task_id: String?
        var id: String { "\(ts ?? 0)-\(type ?? "")-\(summary ?? "")" }

        /// What to show: the summary when there is one, else the event
        /// type, which is at least true.
        var line: String {
            let said = (summary ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return said.isEmpty ? (type ?? "") : said
        }

        var detail: String? {
            let bits = [tool, type].compactMap { $0 }.filter { !$0.isEmpty }
            return bits.isEmpty ? nil : bits.joined(separator: " · ")
        }
    }

    /// One event from `/api/logs` -- a tail of any ledger stream, which is
    /// what "structured logs are Ledger events" means in practice.
    struct LogEvent: Identifiable, Decodable {
        let seq: Int?
        let ts: Double?
        let type: String?
        let payload: [String: AnyCodable]?
        var id: String { "\(seq ?? 0)-\(ts ?? 0)" }

        var summary: String {
            guard let payload else { return "" }
            for key in ["summary", "detail", "text", "result_summary", "reason", "message", "error"] {
                if let found = payload[key]?.text, !found.isEmpty { return found }
            }
            return payload.keys.sorted().prefix(4).joined(separator: ", ")
        }
    }

    /// Ledger payloads are free-form, so decode them loosely and render
    /// what is readable rather than refusing the whole event.
    struct AnyCodable: Decodable {
        let text: String?
        init(from decoder: Decoder) throws {
            let single = try decoder.singleValueContainer()
            if let value = try? single.decode(String.self) { text = value }
            else if let value = try? single.decode(Bool.self) { text = String(value) }
            else if let value = try? single.decode(Double.self) {
                text = value == value.rounded() ? String(Int(value)) : String(value)
            } else { text = nil }
        }
    }

    // MARK: - Calls

    /// Pairing is the one call with no token: it SPENDS a code Sim minted
    /// locally and cannot create one.
    func pair(code: String) async throws -> Paired {
        try await send("/api/pair", method: "POST", body: ["code": code], authed: false)
    }

    func status() async throws -> Status { try await send("/api/status", method: "GET") }

    /// One thing in the house, as `home_find` reports it.
    struct Entity: Identifiable, Decodable, Hashable {
        let entity_id: String
        let name: String?
        let state: String?
        let domain: String?
        let unit: String?
        var available: Bool = true
        var id: String { entity_id }

        var label: String { name ?? entity_id }
        var on: Bool { (state ?? "").lowercased() == "on" }
        /// Something with an on/off service, as opposed to a reading.
        var switchable: Bool {
            ["light", "switch", "fan", "media_player", "input_boolean", "siren"].contains(domain ?? "")
        }
        var reading: String {
            let value = state ?? ""
            guard let unit, !unit.isEmpty else { return value }
            return "\(value) \(unit)"
        }
    }

    struct ActionResult: Decodable {
        let text: String?
        let rows: [Entity]?
        let error: String?
    }

    /// Ask Sim to do one thing. It goes through Guardian exactly as a tool
    /// call from a spoken turn does -- this is not a back door, it is the
    /// same door.
    @discardableResult
    func action(_ tool: String, _ args: [String: Any] = [:]) async throws -> ActionResult {
        try await send("/api/action", method: "POST", body: ["tool": tool, "args": args], timeout: 60)
    }

    /// Everything in the house.
    ///
    /// `home_find`'s structured rows live on the tool's `metadata`, and the
    /// HTTP path carries only the tool's TEXT -- `_run_tool` builds its
    /// Outcome from `stdout_preview` and drops the rest. So this parses
    /// what `Entity.render()` writes:
    ///
    ///     light.kitchen  on  (Kitchen)
    ///     sensor.hall_temp  21.5 °C
    ///     lock.front  locked  (Front door)  [unavailable]
    ///
    /// Parsing text is not the shape I would choose. It is honest about
    /// what the server offers today, and the alternative -- carrying
    /// `metadata` through `action.result` -- is a contracts change, not an
    /// app one.
    func house() async throws -> [Entity] {
        let result = try await action("home_find", ["query": ""])
        if let rows = result.rows, !rows.isEmpty { return rows }
        return (result.text ?? "").split(separator: "\n").compactMap(Self.entity)
    }

    static func entity(from line: any StringProtocol) -> Entity? {
        var rest = line.trimmingCharacters(in: .whitespaces)
        guard !rest.isEmpty, rest.contains(".") else { return nil }
        let available = !rest.contains("[unavailable]")
        rest = rest.replacingOccurrences(of: "[unavailable]", with: "")
                   .trimmingCharacters(in: .whitespaces)

        var name: String?
        if rest.hasSuffix(")"), let open = rest.lastIndex(of: "(") {
            name = String(rest[rest.index(after: open)..<rest.index(before: rest.endIndex)])
            rest = String(rest[rest.startIndex..<open]).trimmingCharacters(in: .whitespaces)
        }
        let parts = rest.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
        guard let id = parts.first, id.contains(".") else { return nil }
        let value = parts.dropFirst().first
        let unit = parts.count > 2 ? parts.dropFirst(2).joined(separator: " ") : nil
        return Entity(entity_id: id, name: name, state: value,
                      domain: String(id.split(separator: ".").first ?? ""),
                      unit: unit, available: available)
    }

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
        struct Wrapper: Decodable { let events: [ActivityRow]? }
        let wrapped: Wrapper = try await send("/api/activity?limit=60", method: "GET")
        return wrapped.events ?? []
    }

    /// A tail of one ledger stream. `system` is Sim's own console; every
    /// other stream is reachable by name, which is what `/api/streams`
    /// lists.
    func logs(stream: String = "system", limit: Int = 100) async throws -> [LogEvent] {
        struct Wrapper: Decodable { let events: [LogEvent]? }
        let wrapped: Wrapper = try await send("/api/logs?stream=\(stream)&limit=\(limit)", method: "GET")
        return wrapped.events ?? []
    }

    /// The lines Sim actually printed -- its terminal, glyphs and all.
    func console(limit: Int = 300, contains: String = "") async throws -> [String] {
        struct Wrapper: Decodable { let lines: [String]? }
        let escaped = contains.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let filter = contains.isEmpty ? "" : "&contains=\(escaped)"
        let wrapped: Wrapper = try await send("/api/console?limit=\(limit)\(filter)", method: "GET")
        return wrapped.lines ?? []
    }

    /// One typed line, through `_handle_line` -- the keyboard's own path,
    /// so Guardian gates whatever it starts exactly as it does at the
    /// terminal. It answers only COMMANDS; a line that parses as chat is
    /// refused and pointed at `/api/chat`.
    @discardableResult
    func command(_ line: String) async throws -> String {
        struct Reply: Decodable { let text: String? }
        let reply: Reply = try await send("/api/command", method: "POST",
                                          body: ["line": line], timeout: 120)
        return reply.text ?? ""
    }

    func streams() async throws -> [String] {
        struct Wrapper: Decodable { let streams: [String]? }
        let wrapped: Wrapper = try await send("/api/streams", method: "GET")
        return wrapped.streams ?? []
    }

    /// What `/api/dash/streams` really returns, read off the server rather
    /// than guessed: `cameras` are STILLS (`/cameras/snap/...`) and
    /// `streams` are live HLS relays, which exist only while something has
    /// started one. Guessing `channel`/`id` here showed an empty tab.
    struct Feeds: Decodable {
        struct Still: Decodable {
            let name: String
            let safe: String?
            let kind: String?
            let url: String?
            let at: Double?
        }
        struct Live: Decodable {
            let channel: Int?
            let name: String?
            let url: String?
            let live: Bool?
            let at: Double?
            /// "sub" or "main". A phone showing ONE camera wants main; the
            /// dashboard's seven-up strip wants sub.
            let quality: String?
        }
        let cameras: [Still]?
        let streams: [Live]?
    }

    func feeds() async throws -> Feeds {
        try await send("/api/dash/streams", method: "GET")
    }

    /// A URL on Sim with the token in the QUERY -- an `AVPlayer` and an
    /// `AsyncImage` cannot set a header, which is the whole reason
    /// `?token=` exists on this server.
    // MARK: - Sim's own voice and ears

    /// What `/api/say` gives back: Kokoro's WAV, and whose voice it is.
    struct Spoken {
        let wav: Data
        let engine: String
    }

    /// Sim synthesises the sentence with its OWN engine and hands back the
    /// audio. The app plays those bytes, so the voice on the phone is the
    /// voice in the kitchen -- "I want to have same voice chat experience
    /// as I have on mac with same stt and tts engines" (the creator,
    /// 2026-09-24). A throw here is not fatal: `VoiceChat` falls back to
    /// the phone's own synthesiser rather than going silent.
    ///
    /// 60 s, not the usual 20: Kokoro is fast but the first call after a
    /// boot loads the model, and a timeout there would make Sim's real
    /// voice look broken exactly once per restart -- the one time a person
    /// is listening for it.
    func say(_ text: String, voice: String = "", speed: Double = 0) async throws -> Spoken {
        var body: [String: Any] = ["text": text]
        if !voice.isEmpty { body["voice"] = voice }
        if speed > 0 { body["speed"] = speed }
        let (data, response) = try await raw("/api/say", method: "POST",
                                            json: body, timeout: 60)
        let http = response as? HTTPURLResponse
        let status = http?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw Failure(status: status, detail: Self.reason(from: data) ?? "Sim answered \(status)")
        }
        guard !data.isEmpty else { throw Failure(status: 502, detail: "Sim sent no audio") }
        return Spoken(wav: data, engine: http?.value(forHTTPHeaderField: "X-Sim-Engine") ?? "")
    }

    struct Heard: Decodable {
        let text: String?
        let confidence: Double?
        let language: String?
        let engine: String?
    }

    /// The phone's recording, transcribed by Sim's own recogniser -- the
    /// same whisper.cpp the Mac listens with, so Farsi and English behave
    /// the same way in both rooms. 120 s: a long turn through a large
    /// model on a busy Mac is slow, and the alternative to waiting is
    /// losing what somebody said.
    func listen(wav: Data, language: String = "") async throws -> Heard {
        let path = language.isEmpty ? "/api/listen" : "/api/listen?language=\(language)"
        let (data, response) = try await raw(path, method: "POST", bytes: wav,
                                             contentType: "audio/wav", timeout: 120)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw Failure(status: status, detail: Self.reason(from: data) ?? "Sim answered \(status)")
        }
        return try JSONDecoder().decode(Heard.self, from: data)
    }

    /// `send` decodes JSON; these two routes carry audio in one direction
    /// or the other, so they need the bytes and the headers themselves.
    private func raw(_ path: String, method: String,
                     json: [String: Any]? = nil,
                     bytes: Data? = nil,
                     contentType: String = "application/json",
                     timeout: TimeInterval) async throws -> (Data, URLResponse) {
        guard let url = URL(string: baseURL + path) else {
            throw Failure(status: 0, detail: "that is not a usable address for Sim")
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        if let json { request.httpBody = try JSONSerialization.data(withJSONObject: json) }
        if let bytes { request.httpBody = bytes }
        do {
            return try await URLSession.shared.data(for: request)
        } catch {
            throw Failure(status: 0, detail: Self.unreachable(baseURL, error))
        }
    }

    func url(_ path: String) -> URL? {
        guard let token else { return URL(string: baseURL + path) }
        let join = path.contains("?") ? "&" : "?"
        return URL(string: "\(baseURL)\(path)\(join)token=\(token)")
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
            // the least useful thing an app can say -- and on a LOCAL
            // address the usual cause is not the network at all.
            throw Failure(status: 0, detail: Self.unreachable(baseURL, error))
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw Failure(status: status, detail: Self.reason(from: data) ?? "Sim answered \(status)")
        }
        if T.self == Empty.self, let empty = Empty() as? T { return empty }
        return try JSONDecoder().decode(T.self, from: data)
    }

    struct Empty: Decodable {}

    /// Why Sim could not be reached, in words that say what to DO.
    ///
    /// iOS asks once for Local Network permission and, if that prompt is
    /// dismissed, blocks every local address from then on with an ordinary
    /// connection error -- indistinguishable from the house being down.
    /// An app cannot detect the denial or ask again, so the only help it
    /// can give is to name it (the creator, 2026-09-25: "could not reach
    /// sim at http://192.168.50.33:8765", with Sim running and answering
    /// on that exact address).
    static func unreachable(_ baseURL: String, _ error: Error) -> String {
        var said = "could not reach Sim at \(baseURL) -- \(error.localizedDescription)"
        if isLocal(baseURL) {
            said += "\n\nIf Sim is running, this is usually iOS Local Network permission: "
            said += "Settings -> Privacy & Security -> Local Network -> Sim. "
            said += "Check by opening \(baseURL)/api/status in Safari: if that works and this does not, "
            said += "it is the permission."
        }
        return said
    }

    /// A private address, where the Local Network prompt applies.
    static func isLocal(_ baseURL: String) -> Bool {
        guard let host = URLComponents(string: baseURL)?.host else { return false }
        if host == "localhost" || host.hasSuffix(".local") { return true }
        let parts = host.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4 else { return false }
        if parts[0] == 10 || (parts[0] == 127) { return true }
        if parts[0] == 192 && parts[1] == 168 { return true }
        if parts[0] == 172 && (16...31).contains(parts[1]) { return true }
        return false
    }

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
