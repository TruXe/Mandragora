import QtQuick
import QtQuick.Layouts

ColumnLayout {
    Text { text: "Welcome back, Alex! 👋"; font.pixelSize: 28 }
    RowLayout {
        StatTile { label: "Sales"; delta: "+12.5%" }
        StatTile { label: "Visitors"; delta: "+8.2%" }
        StatTile { label: "Orders"; delta: "-3.1%" }
    }
}
