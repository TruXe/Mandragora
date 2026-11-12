package app.dashboard

import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.runtime.Composable

@Composable
fun Dashboard() {
    LazyVerticalGrid(columns = GridCells.Fixed(2)) {
        item { StatCard(title = "Revenue", value = "$12,400", delta = "+12.5%") }
        item { StatCard(title = "Users", value = "1,204", delta = "+8.1%") }
        item { StatCard(title = "Orders", value = "342", delta = "+4.0%") }
        item { StatCard(title = "Conversion", value = "3.2%", delta = "-0.4%") }
    }
}
