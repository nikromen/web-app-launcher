import QtQuick
import "UiMetrics.mjs" as UiMetrics
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: appDialog
    property bool blockCloseShortcut: false
    title: dialogController.isAppEditMode ? "Edit Application" : "New Application"
    modal: true

    width: Math.min(Screen.desktopAvailableWidth * UiMetrics.appDialogWidthFraction, UiMetrics.appDialogMaxWidth)
    padding: UiMetrics.dialogPadding

    contentItem: ScrollView {
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        implicitHeight: Math.min(Screen.desktopAvailableHeight * UiMetrics.scrollContentHeightFraction, contentLayout.implicitHeight)

        ColumnLayout {
            id: contentLayout
            width: appDialog.availableWidth
            spacing: UiMetrics.spaceSection

            GroupBox {
                Layout.fillWidth: true
                title: "Basic Information"

                GridLayout {
                    columns: UiMetrics.formColumns
                    columnSpacing: UiMetrics.spaceLarge
                    rowSpacing: UiMetrics.spaceRegular
                    width: parent.width

                    Label {
                        text: "Name *"
                        Layout.alignment: Qt.AlignTop
                        Layout.minimumWidth: UiMetrics.formLabelMinimumWidth
                    }
                    TextField {
                        id: nameField
                        Layout.fillWidth: true
                        placeholderText: "e.g., Gmail, GitHub, Slack..."
                        text: dialogController.appName
                        onTextChanged: dialogController.appName = text
                    }

                    Label {
                        text: "URL *"
                        Layout.alignment: Qt.AlignTop
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            id: urlField
                            Layout.fillWidth: true
                            placeholderText: "https://example.com"
                            text: dialogController.appUrl
                            onTextChanged: dialogController.appUrl = text
                        }
                        Button {
                            text: "Fetch Info"
                            icon.name: "download"
                            onClicked: dialogController.fetch_metadata()
                            enabled: urlField.text.length > 0
                            ToolTip.visible: hovered
                            ToolTip.text: "Download the page title, description, and icon from the URL."
                        }
                    }

                    Label {
                        text: "Description"
                        Layout.alignment: Qt.AlignTop
                    }
                    TextArea {
                        id: descriptionField
                        Layout.fillWidth: true
                        Layout.preferredHeight: UiMetrics.appDescriptionHeight
                        placeholderText: "Brief description of the application..."
                        text: dialogController.appDescription
                        onTextChanged: dialogController.appDescription = text
                        wrapMode: TextArea.Wrap
                    }

                    Label {
                        text: "Icon"
                        Layout.alignment: Qt.AlignVCenter
                    }
                    RowLayout {
                        spacing: UiMetrics.spaceLarge

                        Rectangle {
                            width: UiMetrics.iconPreviewSize
                            height: UiMetrics.iconPreviewSize
                            radius: UiMetrics.iconCornerRadius
                            color: palette.alternateBase
                            border.color: palette.mid
                            border.width: UiMetrics.borderWidth

                            Image {
                                id: iconPreview
                                anchors.centerIn: parent
                                width: UiMetrics.iconPreviewImageSize
                                height: UiMetrics.iconPreviewImageSize
                                source: dialogController.iconPath
                                fillMode: Image.PreserveAspectFit
                                cache: false
                                smooth: true
                                visible: status === Image.Ready
                            }

                            Label {
                                anchors.centerIn: parent
                                text: dialogController.appName ? dialogController.appName.substring(0, 1).toUpperCase() : "A"
                                font.pixelSize: UiMetrics.fontIconPlaceholder
                                font.weight: Font.DemiBold
                                opacity: UiMetrics.opacityPlaceholder
                                visible: !iconPreview.visible
                            }
                        }

                        Button {
                            text: "Choose Icon..."
                            icon.name: "document-open"
                            onClicked: dialogController.choose_icon_file()
                        }
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "Browser Configuration"

                GridLayout {
                    columns: UiMetrics.formColumns
                    columnSpacing: UiMetrics.spaceLarge
                    rowSpacing: UiMetrics.spaceRegular
                    width: parent.width

                    Label {
                        text: "Browser"
                        Layout.minimumWidth: UiMetrics.formLabelMinimumWidth
                    }
                    ComboBox {
                        id: browserCombo
                        Layout.fillWidth: true
                        model: dialogController.browserListModel
                        textRole: "name"
                        currentIndex: dialogController.browserListModel.get_index_by_value(dialogController.selectedBrowserKey)
                        onCurrentIndexChanged: {
                            let key = dialogController.browserListModel.get_value_by_index(currentIndex)
                            dialogController.selectedBrowserKey = key
                        }
                    }

                    RowLayout {
                        spacing: UiMetrics.spaceTiny
                        Layout.minimumWidth: UiMetrics.formLabelMinimumWidth
                        Label { text: "Profile mode" }
                        HelpTip {
                            tipText: "Shared — use an existing profile directly; cookies and extensions are shared with other apps on the same profile.\n\n" +
                                     "Dedicated — this app gets its own profile folder. Copy a template or start empty; changes stay with this app only.\n\n" +
                                     "Session template — each launch starts from a copy of the selected profile. Session data is discarded when the app closes."
                        }
                    }
                    ComboBox {
                        id: profileModeCombo
                        Layout.fillWidth: true
                        model: dialogController.profileModeListModel
                        textRole: "name"
                        currentIndex: dialogController.profileModeListModel.get_index_by_value(dialogController.profileMode)
                        onCurrentIndexChanged: {
                            let mode = dialogController.profileModeListModel.get_value_by_index(currentIndex)
                            dialogController.profileMode = mode
                        }
                    }

                    Item {
                        Layout.columnSpan: UiMetrics.formColumns
                        Layout.fillWidth: true
                        implicitHeight: profileModeDescriptionLabel.implicitHeight

                        Label {
                            id: profileModeDescriptionLabel
                            width: parent.width
                            wrapMode: Text.WordWrap
                            opacity: UiMetrics.opacityDescription
                            font.pixelSize: UiMetrics.fontSecondary
                            text: dialogController.profileModeDescription
                        }
                    }

                    RowLayout {
                        spacing: UiMetrics.spaceTiny
                        Layout.minimumWidth: UiMetrics.formLabelMinimumWidth
                        visible: dialogController.profileSourceEnabled
                        Label {
                            text: dialogController.profileMode === "dedicated" ? "Template profile" : "Source profile"
                        }
                        HelpTip {
                            tipText: {
                                if (dialogController.profileMode === "shared") {
                                    return "Select the profile this app will use directly."
                                }
                                if (dialogController.profileMode === "dedicated") {
                                    return "Optional template to copy when creating this app's profile. Choose \"Empty profile\" to start from scratch."
                                }
                                return "Profile copied at launch. Configure extensions and logins in Profile Manager; they apply on the next start."
                            }
                        }
                    }
                    ComboBox {
                        id: profileCombo
                        Layout.fillWidth: true
                        visible: dialogController.profileSourceEnabled
                        model: dialogController.filteredProfileModel
                        textRole: "name"
                        currentIndex: dialogController.filteredProfileModel.get_index_by_value(dialogController.selectedProfileUuid)
                        onCurrentIndexChanged: {
                            if (currentIndex > -1) {
                                let uuid = dialogController.filteredProfileModel.get_value_by_index(currentIndex)
                                dialogController.selectedProfileUuid = uuid
                            }
                        }
                    }

                    Label {
                        Layout.columnSpan: UiMetrics.formColumns
                        Layout.fillWidth: true
                        visible: !dialogController.profileSourceEnabled && dialogController.dedicatedProfileSummary.length > 0
                        wrapMode: Text.WordWrap
                        opacity: UiMetrics.opacityDescription
                        font.pixelSize: UiMetrics.fontSecondary
                        text: dialogController.dedicatedProfileSummary
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "Options"

                ColumnLayout {
                    width: parent.width
                    CheckBox {
                        id: incognitoCheck
                        text: "Private/Incognito Mode"
                        checked: dialogController.incognitoMode
                        onCheckedChanged: dialogController.incognitoMode = checked
                    }
                    CheckBox {
                        id: navBarCheck
                        text: "Show Navigation Bar"
                        checked: dialogController.showNavigationBar
                        onCheckedChanged: dialogController.showNavigationBar = checked
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "Advanced"

                GridLayout {
                    columns: UiMetrics.formColumns
                    columnSpacing: UiMetrics.spaceLarge
                    rowSpacing: UiMetrics.spaceRegular
                    width: parent.width

                    RowLayout {
                        spacing: UiMetrics.spaceTiny
                        Layout.minimumWidth: UiMetrics.formLabelMinimumWidth
                        Label { text: "Extra Arguments" }
                        HelpTip {
                            tipText: "Extra flags appended to the browser launch command. Separate values with spaces, for example: --new-window"
                        }
                    }
                    TextField {
                        id: extraArgsField
                        Layout.fillWidth: true
                        placeholderText: "Additional command line arguments..."
                        text: dialogController.extraArgs
                        onTextChanged: dialogController.extraArgs = text
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "System Tray"

                ColumnLayout {
                    width: parent.width
                    spacing: UiMetrics.spaceRegular

                    RowLayout {
                        spacing: UiMetrics.spaceTiny
                        CheckBox {
                            id: trayEnabledCheck
                            text: "Enable system tray while this app is running"
                            checked: dialogController.trayEnabled
                            onCheckedChanged: dialogController.trayEnabled = checked
                        }
                        HelpTip {
                            tipText: "Shows a tray icon while the app is running. Right-click for Show, Stop, and any custom actions you add below."
                        }
                    }

                    GridLayout {
                        enabled: trayEnabledCheck.checked
                        visible: trayEnabledCheck.checked
                        columns: UiMetrics.formColumns
                        columnSpacing: UiMetrics.spaceLarge
                        rowSpacing: UiMetrics.spaceCompact
                        Layout.fillWidth: true

                        RowLayout {
                            spacing: UiMetrics.spaceTiny
                            Layout.alignment: Qt.AlignVCenter
                            Layout.minimumWidth: UiMetrics.formLabelMinimumWidth
                            Label { text: "Show command" }
                            HelpTip {
                                tipText: "Optional shell command run via bash -c when you choose Show from the tray. Built-in window focus is used only if this is empty or the command fails. Often needed on Wayland. Environment: WEBAPP_ACTION=show, WEBAPP_UUID, WEBAPP_NAME, WEBAPP_URL, WEBAPP_PID, WEBAPP_PROFILE_PATH."
                            }
                        }
                        TextField {
                            Layout.fillWidth: true
                            placeholderText: 'e.g. wmctrl -a "$WEBAPP_NAME"'
                            text: dialogController.showScriptCommand
                            onTextChanged: dialogController.showScriptCommand = text
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: trayEnabledCheck.checked
                        enabled: trayEnabledCheck.checked
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: UiMetrics.spaceTiny
                            Label {
                                text: "Custom actions"
                                Layout.fillWidth: true
                                font.weight: Font.DemiBold
                            }
                            HelpTip {
                                tipText: "Shell commands added to the tray menu. Each runs via bash -c with WEBAPP_ACTION=script and the same WEBAPP_* environment variables as the show command."
                            }
                        }
                        Button {
                            text: "Add Action"
                            icon.name: "list-add"
                            onClicked: dialogController.add_tray_script()
                        }
                    }

                    Frame {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(UiMetrics.trayScriptsMaxHeight, trayScriptsList.contentHeight + UiMetrics.spaceLarge)
                        visible: trayEnabledCheck.checked && trayScriptsList.count > 0
                        enabled: trayEnabledCheck.checked

                        ListView {
                            id: trayScriptsList
                            anchors.fill: parent
                            anchors.margins: UiMetrics.spaceCompact
                            spacing: UiMetrics.spaceMedium
                            clip: true
                            model: dialogController.trayScriptListModel

                            delegate: ColumnLayout {
                                required property string name
                                required property string description
                                required property int index

                                width: trayScriptsList.width
                                spacing: UiMetrics.spaceSmall

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: UiMetrics.spaceCompact

                                    Label {
                                        text: "Name"
                                        Layout.preferredWidth: UiMetrics.scriptLabelWidth
                                    }
                                    TextField {
                                        id: actionNameField
                                        Layout.fillWidth: true
                                        text: name
                                        placeholderText: "Menu label"
                                        onTextChanged: dialogController.update_tray_script_at_index(
                                            index, text, actionCommandField.text)
                                    }
                                    Button {
                                        text: "Remove"
                                        flat: true
                                        onClicked: dialogController.remove_tray_script_at_index(index)
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: UiMetrics.spaceCompact

                                    Label {
                                        text: "Command"
                                        Layout.preferredWidth: UiMetrics.scriptLabelWidth
                                        Layout.alignment: Qt.AlignTop
                                        topPadding: UiMetrics.spaceCompact
                                    }
                                    TextField {
                                        id: actionCommandField
                                        Layout.fillWidth: true
                                        text: description
                                        placeholderText: 'e.g. notify-send "Hello"'
                                        onTextChanged: dialogController.update_tray_script_at_index(
                                            index, actionNameField.text, text)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    footer: DialogButtonBox {
        Button {
            id: cancelButton
            text: "Cancel"
            flat: true
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }

        Button {
            id: saveButton
            text: dialogController.isAppEditMode ? "Save" : "Create"
            highlighted: true
            enabled: nameField.text.length > 0 && urlField.text.length > 0
            onClicked: dialogController.save_app()
        }
    }

    Shortcut {
        sequence: StandardKey.Save
        enabled: appDialog.visible && saveButton.enabled
        onActivated: dialogController.save_app()
    }
    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: appDialog.visible && !appDialog.blockCloseShortcut
        onActivated: appDialog.close()
    }
}
