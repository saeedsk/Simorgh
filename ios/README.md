# The Sim iPhone app

A native SwiftUI client. It is a **sibling project**, not a package: this
repository is stdlib-only Python by charter, and the app consumes the same
documented HTTP API any other client would (`docs/plan/stage-12-phone-client.md`).

## Getting it onto a phone

1. Xcode -> Settings -> Accounts -> **+** -> your Apple ID. A free account
   gives you a *Personal Team*, which is enough.
2. `open ios/Simorgh.xcodeproj`, select the **Simorgh** target ->
   Signing & Capabilities -> Team = your Personal Team. `PRODUCT_BUNDLE_IDENTIFIER`
   must be globally unique, so change `house.simorgh.app` if Xcode objects.
3. On the phone: Settings -> Privacy & Security -> **Developer Mode** -> on (it reboots).
4. Pick the phone in Xcode's device menu, press **Run**. First launch is
   refused until Settings -> General -> VPN & Device Management -> Trust.

**A free account's build stops launching after 7 days** and needs Run
again; there is no TestFlight without the paid programme, so every phone
must be plugged into this Mac. That, more than the entitlements, is what
the $99 buys.

## Pairing it with Sim

On Sim: `pair my phone` -- or `pair my phone with approve` if this device
should be able to answer Guardian's questions. A barcode appears; scan it.

The barcode carries a pairing **code**, never a token: single use, 120
seconds, in the URL fragment. The app spends it at `POST /api/pair` and
gets its own token, which lives in the Keychain (`WhenUnlockedThisDeviceOnly`,
so it is not in a backup). Revoke a lost phone with `devices revoke <name>`
on Sim -- "Forget this pairing" in the app only clears the local copy.

## What it does

| tab | |
|---|---|
| **Ask** | The thread. One `session_id` per app launch, so Sim's memory groups it as one conversation |
| **House** | What Sim is waiting to be told, with Approve/Deny -- and what it has been doing |
| **Cameras** | Live HLS, which iOS plays natively |
| **Settings** | This device's capabilities, Sim's address, forget the pairing |

**Home** (lights, scenes, thermostats) is absent until stage 12 item 3a
lands `POST /api/action`. A tab with nothing to call would be a button that
lies.

## Where it points

Default `http://192.168.50.33:8765`, changeable in Settings. Plain HTTP is
allowed to the **local network only** (`NSAllowsLocalNetworking`), so the
app works on the house wifi today and a rendezvous on the internet still
has to be `https`. Voice needs no TLS on a native client, which is the one
real advantage native has over a web app here.

## Checking a change before handing it over

`BUILD SUCCEEDED` is not enough: a simulator build never validates the
bundle, so an app with no `CFBundleIdentifier` compiles happily and cannot
be installed anywhere (2026-09-25). Install it:

    xcrun simctl boot 'iPhone 15 Pro'
    xcrun simctl install booted <path>/Simorgh.app
    xcrun simctl launch booted house.simorgh.app

`Info.plist` is supplied rather than generated (the local-network exception
needs it), which means EVERY key Xcode would have generated has to be in
it. Leave one out and the failure appears at install time, on a phone.

## Building it without Xcode open

    xcodebuild -project ios/Simorgh.xcodeproj -target Simorgh \
      -sdk iphonesimulator -configuration Debug -arch arm64 build

That is how every commit here was checked. A device build needs a signing
identity and belongs in Xcode.
