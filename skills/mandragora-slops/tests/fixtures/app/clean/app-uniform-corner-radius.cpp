#include "imgui.h"

void ApplyTheme()
{
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding = 0.0f;   // panels dock edge to edge
    style.FrameRounding = 3.0f;    // inputs and buttons
    style.GrabRounding = 2.0f;     // slider grabs
    style.PopupRounding = 6.0f;    // popups float above content
}
