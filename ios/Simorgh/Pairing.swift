import AVFoundation
import SwiftUI

/// Scanning the barcode Sim draws in its terminal.
///
/// The QR carries a pairing CODE in the URL fragment, never a token: single
/// use, 120 seconds, one outstanding. So a photograph of Sim's screen is
/// worth nothing a minute later, and this app gets its own token by
/// spending the code at `POST /api/pair`.
struct PairingView: View {
    @EnvironmentObject var store: Store
    @State private var typed = ""
    @State private var problem: String?
    @State private var busy = false
    @State private var scanning = true

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                if scanning {
                    ScannerView { scanned in
                        guard !busy else { return }
                        scanning = false
                        Task { await pair(with: Self.code(in: scanned) ?? scanned) }
                    }
                    .frame(height: 300)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(.secondary.opacity(0.3)))
                } else {
                    ProgressView().frame(height: 300)
                }

                Text("On Sim, type  pair my phone")
                    .font(.headline)
                Text("Add  with approve  if this phone should be able to answer Guardian's questions.")
                    .font(.footnote).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)

                LabeledContent("Sim's address") {
                    TextField("http://…", text: $store.baseURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .multilineTextAlignment(.trailing)
                }
                HStack {
                    TextField("or type the code", text: $typed)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Pair") { Task { await pair(with: typed) } }
                        .disabled(typed.isEmpty || busy)
                }
                if let said = problem {
                    Text(said).font(.footnote).foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                    Button("Scan again") { problem = nil; scanning = true }
                }
                Spacer()
            }
            .padding()
            .navigationTitle("Pair with Sim")
        }
    }

    /// The code out of `https://host/pair#CODE`, or nil if this was not one
    /// of Sim's barcodes. Accepting any old string would mean a random QR
    /// looked like a failed pairing rather than the wrong barcode.
    static func code(in text: String) -> String? {
        guard let hash = text.firstIndex(of: "#"), text.contains("/pair") else { return nil }
        let code = String(text[text.index(after: hash)...])
        return code.isEmpty ? nil : code
    }

    private func pair(with code: String) async {
        busy = true
        defer { busy = false }
        do {
            let paired = try await Api(baseURL: store.baseURL, token: nil).pair(code: code)
            store.save(token: paired.token, name: paired.name, capabilities: paired.capabilities)
        } catch {
            problem = error.localizedDescription
            scanning = false
        }
    }
}

/// A camera preview that reports the QRs it sees. UIKit, because
/// AVCaptureSession has no SwiftUI equivalent.
struct ScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        let controller = ScannerController()
        controller.onCode = onCode
        return controller
    }

    func updateUIViewController(_ controller: ScannerController, context: Context) {}
}

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let session = AVCaptureSession()
    private var layer: AVCaptureVideoPreviewLayer?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .secondarySystemBackground
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input)
        else { return }              // no camera: the typed code still works
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        preview.frame = view.bounds
        view.layer.addSublayer(preview)
        layer = preview
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        layer?.frame = view.bounds
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        if !session.isRunning {
            // Off the main thread: starting a capture session blocks, and
            // blocking here is a visible stutter as the view appears.
            Task.detached { [session] in session.startRunning() }
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning { session.stopRunning() }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput,
                        didOutput objects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        guard let first = objects.first as? AVMetadataMachineReadableCodeObject,
              let text = first.stringValue else { return }
        session.stopRunning()
        onCode?(text)
    }
}
