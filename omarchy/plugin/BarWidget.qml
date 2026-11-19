import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BarWidget {
    id: root
    moduleName: "community.bitwarden-window"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    property double deadlineMs: 0
    property double nowMs: Date.now()
    property double lastProbeMs: 0
    property Item clickedWidget: null
    property bool popupOpen: false
    readonly property int minutes: Math.ceil(Math.max(0, deadlineMs - nowMs) / 60000)
    readonly property string minuteText: Commons.I18n.formatNumber(minutes)

    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

    function close() { popupOpen = false }

    // Omarchy creates one widget per screen. Share the CLI probe and the
    // password dialog, while keeping each popup anchored to the clicked bar.
    function widgets() {
        const items = bar ? bar.moduleWidgets(moduleName) : []
        return items.length ? items : [root]
    }

    function poll() {
        const primary = widgets()[0]
        if (primary !== root) {
            nowMs = Date.now()
            deadlineMs = primary.deadlineMs
            return
        }
        probe(null, false)
    }

    function probe(clicked, force) {
        if (unlock.running) return
        if (clicked) clickedWidget = clicked
        const elapsed = Date.now() - lastProbeMs
        if (status.running || (!force && elapsed >= 0 && elapsed < 30000)) return
        lastProbeMs = Date.now()
        status.running = true
    }

    function acceptStatus(code, normalExit) {
        const match = normalExit && code === 0 && /^Bitwarden window open; (\d{1,4}) seconds remaining\.$/.exec(output.text.trim())
        const now = Date.now()
        const deadline = match && Number(match[1]) <= 3600 ? now + Math.max(1, Number(match[1])) * 1000 : 0
        for (const widget of widgets()) {
            widget.nowMs = now
            widget.deadlineMs = deadline
            if (!deadline) widget.close()
        }
        const clicked = clickedWidget
        clickedWidget = null
        if (!clicked) return
        if (deadline) clicked.popupOpen = !clicked.popupOpen
        else unlock.running = true
    }

    Timer {
        interval: 45000
        running: true
        repeat: true
        onTriggered: root.poll()
    }
    Component.onCompleted: Qt.callLater(root.poll)

    Timer {
        interval: 1000
        running: root.deadlineMs > 0
        repeat: true
        onTriggered: {
            const now = Date.now()
            const sinceTick = now - root.nowMs
            root.nowMs = now
            if (sinceTick < 0 || sinceTick > 5000) {
                // Reconcile a clock adjustment or resume with the broker's boot clock.
                root.deadlineMs = 0
                root.widgets()[0].probe(null, true)
            } else if (now >= root.deadlineMs) {
                root.deadlineMs = 0
            }
            if (!root.deadlineMs) root.close()
        }
    }

    Process {
        id: status
        command: [Quickshell.env("HOME") + "/.local/bin/bw-window", "status"]
        stdout: StdioCollector { id: output; waitForEnd: true }
        stderr: StdioCollector {}
        onExited: (code, exitStatus) => root.acceptStatus(code, exitStatus === 0)
    }

    Process {
        id: unlock
        command: [decodeURIComponent(Qt.resolvedUrl("bin/unlock").toString().replace(/^file:\/\//, ""))]
        onExited: Qt.callLater(() => root.widgets()[0].probe(null, true))
    }

    WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: root.vertical
            ? (root.minutes ? "BW\n" + root.minuteText + "m" : "BW")
            : (root.minutes ? " BW " + root.minuteText + " min" : " BW")
        tooltipText: root.minutes ? strings.t("remaining").arg(root.minuteText) : strings.t("unlock")
        onPressed: mouseButton => {
            if (mouseButton === Qt.LeftButton)
                root.widgets()[0].probe(root, true)
        }
    }

    PopupCard {
        id: popup
        anchorItem: button
        bar: root.bar
        owner: root
        open: root.popupOpen && root.minutes > 0
        contentWidth: popup.fittedContentWidth(Style.space(250))
        contentHeight: popup.fittedContentHeight(column.implicitHeight)

        Column {
            id: column
            width: parent.width
            spacing: Style.space(6)

            Text {
                textFormat: Text.PlainText
                text: "Bitwarden CLI"
                color: Commons.Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
            }
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                text: strings.t("remaining").arg(root.minuteText)
                color: Commons.Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
            }
        }
    }
}
