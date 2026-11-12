import SwiftUI

struct DeviceRow: View {
    let name: String
    let online: Bool
    let lastSeen: String

    var body: some View {
        HStack {
            Text(name)
            Spacer()
            Text(online ? "Online" : "Offline")
                .foregroundStyle(online ? Color.green : Color.secondary)
            Text(lastSeen)
                .monospacedDigit()
        }
    }
}
