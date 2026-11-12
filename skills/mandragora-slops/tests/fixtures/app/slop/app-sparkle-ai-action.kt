package app.notes

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

@Composable
fun AskAiButton(onAsk: () -> Unit) {
    ExtendedFloatingActionButton(onClick = onAsk) {
        Icon(Icons.Filled.AutoAwesome, contentDescription = null)
        Text("Ask AI")
    }
}
