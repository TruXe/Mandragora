package app.notes

import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable

@Composable
fun NoteActions(onSummarize: () -> Unit, onChecklist: () -> Unit) {
    Row {
        TextButton(onClick = onSummarize) { Text("Summarize note") }
        TextButton(onClick = onChecklist) { Text("Make checklist") }
    }
}
