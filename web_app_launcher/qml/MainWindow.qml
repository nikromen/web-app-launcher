import QtQuick
import "UiMetrics.mjs" as UiMetrics
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: mainWindow
    visible: true

    width: Screen.desktopAvailableWidth * UiMetrics.mainWindowScreenFraction
    height: Screen.desktopAvailableHeight * UiMetrics.mainWindowScreenFraction
    minimumWidth: UiMetrics.mainWindowMinimumWidth
    minimumHeight: UiMetrics.mainWindowMinimumHeight

    title: "Web App Launcher"

    onClosing: function(close) {
        close.accepted = true
        mainController.handle_window_closing()
    }

    function anyModalOpen() {
        return appDialogInstance.visible || profileManagerInstance.visible
            || profileDialogInstance.visible || iconPickerInstance.visible
            || importModeDialog.visible || backupWarningDialog.visible
            || shortcutsDialog.visible || aboutDialog.visible
            || infoMessageDialog.visible || warningMessageDialog.visible
    }

    function selectedAppUuid() {
        if (appsGridView.currentIndex < 0)
            return ""
        return mainController.appListModel.get_app_uuid_by_index(appsGridView.currentIndex)
    }

    function launchSelected() {
        let uuid = selectedAppUuid()
        if (uuid)
            mainController.launch_app(uuid)
    }

    function editSelected() {
        let uuid = selectedAppUuid()
        if (uuid)
            mainController.edit_app(uuid)
    }

    function removeSelected() {
        let uuid = selectedAppUuid()
        if (uuid)
            mainController.remove_app(uuid)
    }

    function gridColumns() {
        return Math.max(1, Math.floor(appsGridView.width / appsGridView.cellWidth))
    }

    function moveGridSelection(rowDelta, colDelta) {
        let count = appsGridView.count
        if (count === 0)
            return

        if (appsGridView.currentIndex < 0) {
            appsGridView.currentIndex = 0
            appsGridView.positionViewAtIndex(0, GridView.Visible)
            return
        }

        let cols = gridColumns()
        let index = appsGridView.currentIndex
        let row = Math.floor(index / cols)
        let col = index % cols
        row += rowDelta
        col += colDelta

        if (col < 0) {
            col = cols - 1
            row -= 1
        } else if (col >= cols) {
            col = 0
            row += 1
        }

        let maxRow = Math.floor((count - 1) / cols)
        row = Math.max(0, Math.min(maxRow, row))
        let newIndex = row * cols + col
        newIndex = Math.max(0, Math.min(count - 1, newIndex))

        appsGridView.currentIndex = newIndex
        appsGridView.positionViewAtIndex(newIndex, GridView.Visible)
    }

    function handleMainEscape() {
        if (searchField.activeFocus && searchField.text.length > 0) {
            searchField.text = ""
            return
        }
        if (searchField.activeFocus) {
            searchField.focus = false
            appsGridView.forceActiveFocus()
            return
        }
        appsGridView.currentIndex = -1
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: UiMetrics.spaceLarge
        spacing: UiMetrics.spaceRegular

        RowLayout {
            Layout.fillWidth: true
            spacing: UiMetrics.spaceCompact

            TextField {
                id: searchField
                Layout.fillWidth: true
                Layout.preferredHeight: UiMetrics.searchFieldHeight
                placeholderText: "Search applications...  (Ctrl+F, /)"
                font.pixelSize: UiMetrics.fontBody
                onTextChanged: mainController.filter_apps(text)
            }

            ToolButton {
                Layout.preferredWidth: UiMetrics.searchButtonSize
                Layout.preferredHeight: UiMetrics.searchFieldHeight
                icon.name: "open-menu"
                display: AbstractButton.IconOnly
                ToolTip.visible: hovered
                ToolTip.text: "Menu"
                onClicked: appMenu.open()

                Menu {
                    id: appMenu
                    MenuItem {
                        text: "Keyboard Shortcuts"
                        icon.name: "input-keyboard"
                        onTriggered: shortcutsDialog.open()
                    }
                    MenuItem {
                        text: "About"
                        icon.name: "help-about"
                        onTriggered: aboutDialog.open()
                    }
                    MenuSeparator { }
                    MenuItem {
                        text: "Quit"
                        icon.name: "application-exit"
                        onTriggered: mainController.quit_application()
                    }
                }
            }
        }

        Frame {
            Layout.fillWidth: true
            Layout.fillHeight: true

            GridView {
                id: appsGridView
                anchors.fill: parent
                anchors.margins: UiMetrics.spaceRegular
                cellWidth: UiMetrics.appGridCellWidth
                cellHeight: UiMetrics.appGridCellHeight
                clip: true
                focus: true
                activeFocusOnTab: true

                model: mainController.appListModel

                Keys.onPressed: (event) => {
                    if (mainWindow.anyModalOpen())
                        return

                    switch (event.key) {
                    case Qt.Key_Up:
                        mainWindow.moveGridSelection(-1, 0)
                        event.accepted = true
                        break
                    case Qt.Key_Down:
                        mainWindow.moveGridSelection(1, 0)
                        event.accepted = true
                        break
                    case Qt.Key_Left:
                        mainWindow.moveGridSelection(0, -1)
                        event.accepted = true
                        break
                    case Qt.Key_Right:
                        mainWindow.moveGridSelection(0, 1)
                        event.accepted = true
                        break
                    case Qt.Key_Home:
                        if (count > 0) {
                            currentIndex = 0
                            positionViewAtIndex(0, GridView.Visible)
                        }
                        event.accepted = true
                        break
                    case Qt.Key_End:
                        if (count > 0) {
                            currentIndex = count - 1
                            positionViewAtIndex(count - 1, GridView.Visible)
                        }
                        event.accepted = true
                        break
                    case Qt.Key_Return:
                    case Qt.Key_Enter:
                        mainWindow.launchSelected()
                        event.accepted = true
                        break
                    case Qt.Key_Delete:
                        mainWindow.removeSelected()
                        event.accepted = true
                        break
                    }
                }

                Connections {
                    target: mainController.appListModel
                    function onModelReset() {
                        appsGridView.currentIndex = -1
                    }
                }

                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: ItemDelegate {
                    width: appsGridView.cellWidth - UiMetrics.spaceCompact
                    height: appsGridView.cellHeight - UiMetrics.spaceCompact
                    highlighted: appsGridView.currentIndex === index

                    contentItem: ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: UiMetrics.spaceRegular
                        spacing: UiMetrics.spaceSmall

                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: UiMetrics.appTileIconSize
                            Layout.alignment: Qt.AlignHCenter | Qt.AlignTop

                            Image {
                                id: appIcon
                                anchors.fill: parent
                                source: model.iconPath
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                visible: source.toString().length > 0
                            }

                            Label {
                                anchors.centerIn: parent
                                text: model.appName.substring(0, 1)
                                font.pixelSize: UiMetrics.fontAppInitial
                                visible: !appIcon.visible
                            }
                        }

                        Label {
                            text: model.appName
                            font.pixelSize: UiMetrics.fontBody
                            font.weight: Font.Medium
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignTop
                            elide: Text.ElideRight
                            wrapMode: Text.WordWrap
                            maximumLineCount: UiMetrics.appTitleMaxLines
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignHCenter | Qt.AlignTop
                        }

                        Label {
                            text: model.profileInfo
                            font.pixelSize: UiMetrics.fontCaption
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignTop
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignHCenter | Qt.AlignTop
                            opacity: UiMetrics.opacityHint
                        }

                        Item { Layout.fillHeight: true }
                    }

                    onClicked: appsGridView.currentIndex = index
                    onDoubleClicked: mainController.launch_app(model.appUuid)

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        onClicked: (mouse) => {
                            if (mouse.button === Qt.RightButton) {
                                appsGridView.currentIndex = index
                                contextMenu.popup()
                            }
                        }

                        Menu {
                            id: contextMenu
                            MenuItem {
                                text: "Launch"
                                icon.name: "media-playback-start"
                                onTriggered: mainController.launch_app(model.appUuid)
                            }
                            MenuItem {
                                text: "Edit"
                                icon.name: "edit-rename"
                                onTriggered: mainController.edit_app(model.appUuid)
                            }
                            MenuSeparator { }
                            MenuItem {
                                text: "Remove"
                                icon.name: "edit-delete"
                                onTriggered: mainController.remove_app(model.appUuid)
                            }
                        }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: appsGridView.count === 0
                    text: "No applications yet.\nClick \"Add Application\" to get started."
                    font.pixelSize: UiMetrics.fontEmptyState
                    opacity: UiMetrics.opacityEmptyState
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: UiMetrics.spaceCompact

            Button {
                text: "Manage Profiles"
                icon.name: "preferences-system"
                flat: true
                onClicked: mainController.open_profile_manager()
            }

            Button {
                text: "Add Application"
                icon.name: "list-add"
                highlighted: true
                onClicked: mainController.add_app()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Import"
                icon.name: "document-open"
                flat: true
                onClicked: mainController.trigger_import_dialog()
            }
            Button {
                text: "Export"
                icon.name: "document-save"
                flat: true
                onClicked: mainController.export_config()
            }
            Button {
                text: "Edit"
                icon.name: "edit-rename"
                enabled: appsGridView.currentIndex >= 0
                onClicked: {
                    if (appsGridView.currentIndex >= 0) {
                        let uuid = mainController.appListModel.get_app_uuid_by_index(appsGridView.currentIndex)
                        mainController.edit_app(uuid)
                    }
                }
            }
            Button {
                text: "Launch"
                icon.name: "media-playback-start"
                enabled: appsGridView.currentIndex >= 0
                highlighted: true
                onClicked: {
                    if (appsGridView.currentIndex >= 0) {
                        let uuid = mainController.appListModel.get_app_uuid_by_index(appsGridView.currentIndex)
                        mainController.launch_app(uuid)
                    }
                }
            }
        }
    }

    AppDialog {
        id: appDialogInstance
        parent: Overlay.overlay
        anchors.centerIn: parent
        blockCloseShortcut: iconPickerInstance.visible
    }

    ProfileManagerDialog {
        id: profileManagerInstance
        parent: Overlay.overlay
        anchors.centerIn: parent
        blockCloseShortcut: profileDialogInstance.visible
    }

    ProfileDialog {
        id: profileDialogInstance
        parent: Overlay.overlay
        anchors.centerIn: parent
    }

    IconPickerDialog {
        id: iconPickerInstance
        parent: Overlay.overlay
        anchors.centerIn: parent
    }

    ShortcutsDialog {
        id: shortcutsDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
    }

    AboutDialog {
        id: aboutDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
    }

    Shortcut {
        sequence: "Ctrl+F"
        enabled: !mainWindow.anyModalOpen()
        onActivated: searchField.forceActiveFocus()
    }
    Shortcut {
        sequence: "/"
        enabled: !mainWindow.anyModalOpen() && !searchField.activeFocus
        onActivated: searchField.forceActiveFocus()
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: !mainWindow.anyModalOpen()
        onActivated: mainController.add_app()
    }
    Shortcut {
        sequence: "F2"
        enabled: !mainWindow.anyModalOpen() && appsGridView.currentIndex >= 0 && !searchField.activeFocus
        onActivated: mainWindow.editSelected()
    }
    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: !mainWindow.anyModalOpen()
        onActivated: mainWindow.handleMainEscape()
    }
    Shortcut {
        sequence: "Ctrl+Shift+P"
        enabled: !mainWindow.anyModalOpen()
        onActivated: mainController.open_profile_manager()
    }
    Shortcut {
        sequence: "Ctrl+Shift+I"
        enabled: !mainWindow.anyModalOpen()
        onActivated: mainController.trigger_import_dialog()
    }
    Shortcut {
        sequence: "Ctrl+Shift+E"
        enabled: !mainWindow.anyModalOpen()
        onActivated: mainController.export_config()
    }

    Connections {
        target: mainController

        function onShowAppDialog(appUuid) {
            dialogController.prepare_app_dialog(appUuid)
            appDialogInstance.open()
        }

        function onShowProfileManager() {
            appDialogInstance.close()
            profileDialogInstance.close()
            iconPickerInstance.close()
            dialogController.prepare_profile_manager()
            profileManagerInstance.z = UiMetrics.dialogZ
            profileManagerInstance.open()
        }

        function onShowImportDialog(filePath) {
            importModeDialog.importFilePath = filePath
            importModeDialog.open()
        }

        function onShowInfoMessage(title, text) {
            infoMessageDialog.title = title
            infoMessageDialog.text = text
            infoMessageDialog.open()
        }

        function onShowWarningMessage(title, text) {
            warningMessageDialog.title = title
            warningMessageDialog.text = text
            warningMessageDialog.open()
        }
    }

    Connections {
        target: dialogController

        function onApp_saved() {
            appDialogInstance.close()
        }

        function onProfile_saved() {
            profileDialogInstance.close()
        }

        function onShowProfileEditDialog(profileUuid) {
            profileDialogInstance.z = profileManagerInstance.visible ? UiMetrics.childDialogZ : UiMetrics.dialogZ
            profileDialogInstance.open()
        }

        function onShowIconPicker(paths) {
            iconPickerInstance.iconPaths = paths
            iconPickerInstance.z = appDialogInstance.visible ? UiMetrics.childDialogZ : UiMetrics.dialogZ
            iconPickerInstance.open()
        }
    }

    Dialog {
        id: importModeDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: "Import Mode"
        modal: true
        width: UiMetrics.messageDialogWidth

        property string importFilePath: ""

        contentItem: Label {
            text: "Do you want to merge with existing configuration?\n\n" +
                  "Yes: Merge (keep existing apps)\n" +
                  "No: Replace (remove all existing apps)"
            wrapMode: Text.WordWrap
            padding: UiMetrics.spaceSection
        }

        footer: DialogButtonBox {
            Button {
                text: "Cancel"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                text: "No (Replace)"
                DialogButtonBox.buttonRole: DialogButtonBox.NoRole
                onClicked: {
                    importModeDialog.close()
                    backupWarningDialog.open()
                }
            }
            Button {
                text: "Yes (Merge)"
                highlighted: true
                DialogButtonBox.buttonRole: DialogButtonBox.YesRole
                onClicked: {
                    importModeDialog.close()
                    mainController.do_import_config(importModeDialog.importFilePath, true)
                }
            }
        }
    }

    Dialog {
        id: backupWarningDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: "Backup Recommendation"
        modal: true
        width: UiMetrics.messageDialogWidth

        contentItem: Label {
            text: "You have chosen to replace your current configuration.\n\n" +
                  "It is strongly recommended to export your current configuration " +
                  "for backup purposes before proceeding.\n\n" +
                  "Do you want to proceed with the import?"
            wrapMode: Text.WordWrap
            padding: UiMetrics.spaceSection
        }

        footer: DialogButtonBox {
            Button {
                text: "No"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                text: "Yes (Proceed)"
                highlighted: true
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
                onClicked: {
                    backupWarningDialog.close()
                    mainController.do_import_config(importModeDialog.importFilePath, false)
                }
            }
        }
    }

    MessageDialog {
        id: infoMessageDialog
        title: "Info"
        buttons: MessageDialog.Ok
    }

    MessageDialog {
        id: warningMessageDialog
        title: "Warning"
        buttons: MessageDialog.Ok
    }
}
