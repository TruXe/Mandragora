import SwiftUI

struct DeviceStatus: View {
    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Color.green)
                .frame(width: 8, height: 8)
            Text("Online")
                .font(.caption)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(Capsule().fill(Color.green.opacity(0.1)))
        .overlay(Capsule().stroke(Color.green, lineWidth: 1))
    }
}
