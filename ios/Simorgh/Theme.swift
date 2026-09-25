import SwiftUI

/// The house palette, from `docs/brand/simorgh-brand.json` -- the file the
/// CLI banner already reads, so the phone and the terminal are the same
/// thing wearing different clothes.
///
/// Gold carries the brand, lapis carries depth, and the other three are
/// signals rather than decoration: emerald for done, crimson for refused,
/// amethyst for Sim's own voice. Colour is never the only carrier -- every
/// state here also has a word or a glyph, because a palette that has to be
/// learnt is a palette that misleads.
enum Brand {
    static let gold = Color(red: 197 / 255, green: 160 / 255, blue: 89 / 255)
    static let goldLight = Color(red: 232 / 255, green: 205 / 255, blue: 148 / 255)
    static let lapis = Color(red: 15 / 255, green: 82 / 255, blue: 186 / 255)
    static let crimson = Color(red: 139 / 255, green: 0, blue: 0)
    static let emerald = Color(red: 80 / 255, green: 200 / 255, blue: 120 / 255)
    static let amethyst = Color(red: 153 / 255, green: 102 / 255, blue: 204 / 255)
    static let night = Color(red: 7 / 255, green: 11 / 255, blue: 26 / 255)

    /// The night-to-lapis wash the icon uses, for screens with no content
    /// of their own to carry.
    static var deep: LinearGradient {
        LinearGradient(colors: [lapis.opacity(0.55), night],
                       startPoint: .top, endPoint: .bottom)
    }
}

/// A card: the one surface shape the app uses, so a card always means
/// "a thing", and spacing does the rest.
struct Card: ViewModifier {
    var tint: Color? = nil

    func body(content: Content) -> some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(tint?.opacity(0.4) ?? Color.clear, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.06), radius: 8, y: 3)
    }
}

extension View {
    func card(tint: Color? = nil) -> some View { modifier(Card(tint: tint)) }
}

/// The mark, drawn rather than shipped as an image so it stays sharp and
/// tints with the view it sits in.
struct Feather: View {
    var size: CGFloat = 64
    var tint: Color = Brand.gold

    var body: some View {
        // The app icon's own feather, so the mark in the app and the mark
        // on the Home Screen are one thing. An SF symbol stood in for it
        // first and read as a leaf, which is the wrong bird entirely.
        Image("Mark")
            .resizable()
            .scaledToFit()
            .padding(size * 0.17)
            .frame(width: size, height: size)
            .background(
                Circle().fill(Brand.deep)
                    .overlay(Circle().stroke(tint.opacity(0.45), lineWidth: 1))
            )
    }
}
