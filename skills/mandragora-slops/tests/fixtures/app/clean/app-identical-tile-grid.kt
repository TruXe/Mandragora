package app.dashboard

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

@Composable
fun Dashboard(revenue: String, trend: List<Float>) {
    Column {
        Text("Revenue this month")
        Text(revenue)
        TrendLine(points = trend)
        MetricRow(label = "Orders", value = "342")
        MetricRow(label = "Users", value = "1,204")
        MetricRow(label = "Refunds", value = "11")
    }
}
