import Foundation
import Vision

struct Options {
    let outputDirectory: URL
    let imagePaths: [String]
    let languages: [String]
}

func parseOptions() -> Options {
    var args = Array(CommandLine.arguments.dropFirst())
    var outputDirectory: URL?
    var languages = ["ko-KR", "en-US"]
    var imagePaths: [String] = []

    while !args.isEmpty {
        let arg = args.removeFirst()
        if arg == "--output-dir", let value = args.first {
            outputDirectory = URL(fileURLWithPath: value, isDirectory: true)
            args.removeFirst()
        } else if arg == "--languages", let value = args.first {
            languages = value.split(separator: ",").map(String.init)
            args.removeFirst()
        } else {
            imagePaths.append(arg)
        }
    }

    guard let outputDirectory, !imagePaths.isEmpty else {
        fputs("Usage: vision_ocr_batch --output-dir <dir> [--languages ko-KR,en-US] <image> ...\n", stderr)
        exit(2)
    }
    return Options(outputDirectory: outputDirectory, imagePaths: imagePaths, languages: languages)
}

func orderedText(for imagePath: String, languages: [String]) throws -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    let supported = (try? VNRecognizeTextRequest.supportedRecognitionLanguages(
        for: .accurate,
        revision: VNRecognizeTextRequest.currentRevision
    )) ?? []
    let selected = languages.filter { supported.contains($0) }
    if !selected.isEmpty {
        request.recognitionLanguages = selected
    }
    request.minimumTextHeight = 0.004

    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: imagePath), options: [:])
    try handler.perform([request])
    let observations = (request.results ?? []).compactMap { observation -> (String, CGRect)? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        return (candidate.string, observation.boundingBox)
    }
    let ordered = observations.sorted {
        let yDelta = abs($0.1.midY - $1.1.midY)
        if yDelta > 0.018 { return $0.1.midY > $1.1.midY }
        return $0.1.minX < $1.1.minX
    }
    return ordered.map(\.0).joined(separator: "\n") + "\n"
}

let options = parseOptions()
try? FileManager.default.createDirectory(
    at: options.outputDirectory,
    withIntermediateDirectories: true,
    attributes: nil
)

for imagePath in options.imagePaths {
    do {
        let text = try orderedText(for: imagePath, languages: options.languages)
        let imageURL = URL(fileURLWithPath: imagePath)
        let outputURL = options.outputDirectory.appendingPathComponent(imageURL.deletingPathExtension().lastPathComponent + ".txt")
        try Data(text.utf8).write(to: outputURL)
        print(outputURL.path)
    } catch {
        let nsError = error as NSError
        fputs(
            "Vision OCR failed for \(imagePath): \(error) (domain=\(nsError.domain), code=\(nsError.code))\n",
            stderr
        )
        exit(1)
    }
}
