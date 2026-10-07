// Big tappable desktop icon for the radio. Bottom layer: above wallpaper, below windows.
import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
  anchors { top: true; left: true }
  margins { top: 12; left: 12 }
  implicitWidth: 100
  implicitHeight: 100
  color: "transparent"
  exclusiveZone: 0 // sit below bar, reserve nothing
  WlrLayershell.layer: WlrLayer.Bottom
  WlrLayershell.namespace: "rpie-desktop-icon"

  Rectangle {
    anchors.fill: parent
    radius: 16
    color: tap.pressed ? "#cc8fbc5a" : "#991a1b26"

    Column {
      anchors.centerIn: parent
      Text { text: "\u{F0439}"; font.pixelSize: 52; color: "#e0e0e0"; anchors.horizontalCenter: parent.horizontalCenter }
      Text { text: "Radio"; font.pixelSize: 16; font.bold: true; color: "#e0e0e0"; anchors.horizontalCenter: parent.horizontalCenter }
    }

    MouseArea {
      id: tap
      anchors.fill: parent
      // login shell so ~/.local/bin is on PATH
      onClicked: Quickshell.execDetached(["bash", "-lc", "radio"])
    }
  }
}
