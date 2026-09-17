import Foundation

public actor DeviceClient {
    public let baseURL: URL
    private var token: String?
    private let session: URLSession
    public init(baseURL: URL, token: String? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL; self.token = token; self.session = session
    }
    public func request(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        guard let url = URL(string: path, relativeTo: baseURL) else { throw URLError(.badURL) }
        var request = URLRequest(url: url); request.httpMethod = method; request.httpBody = body
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw CoreError.rejected(String(data: data, encoding: .utf8) ?? "Device request failed") }
        return data
    }
    public func pair(code: String, name: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["code":code,"name":name])
        let data = try await request("/v1/pair", method: "POST", body: body)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String:String], let token = object["token"] else { throw CoreError.invalidResult }
        self.token = token
    }
    public func startRecording(requestID: UUID = UUID()) async throws -> Data {
        try await request("/v1/recordings/start", method: "POST", body: JSONSerialization.data(withJSONObject: ["request_id":requestID.uuidString]))
    }
    public func stopRecording(requestID: UUID = UUID()) async throws -> Data {
        try await request("/v1/recordings/stop", method: "POST", body: JSONSerialization.data(withJSONObject: ["request_id":requestID.uuidString]))
    }
}
