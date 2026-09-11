%global srcname web_app_launcher

%if 0%{?git_build}
%global pkg_name web-app-launcher-git
%else
%global pkg_name web-app-launcher
%endif


Name:           %{pkg_name}
Version:        0.1.0
Release:        %autorelease
Summary:        Qt-based web application launcher with browser profiles and system tray support

License:        GPL-3.0-or-later
URL:            https://github.com/nikromen/web-app-launcher
Source:         %{srcname}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-hatchling
BuildRequires:  python3-pytest
BuildRequires:  python3-pyside6

Requires:       python3-beautifulsoup4
Requires:       python3-click
Requires:       python3-pillow
Requires:       python3-pydantic
Requires:       python3-pyside6
Requires:       python3-requests

%if 0%{?git_build}
Conflicts:      web-app-launcher
%else
Conflicts:      web-app-launcher-git
%endif


%description
Web App Launcher lets you run web applications as standalone desktop apps
with dedicated browser profiles, optional system tray integration, and
per-app launch settings.
%if 0%{?git_build}

This is a development build from the main branch.
%endif


%prep
%autosetup -n %{srcname}-%{version}


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files %{srcname}

install -Dpm644 data/com.nikromen.WebAppLauncher.desktop \
    %{buildroot}%{_datadir}/applications/com.nikromen.WebAppLauncher.desktop
install -Dpm644 data/com.nikromen.WebAppLauncher.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/com.nikromen.WebAppLauncher.metainfo.xml
install -Dpm644 data/icons/hicolor/scalable/apps/com.nikromen.WebAppLauncher.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/com.nikromen.WebAppLauncher.svg


%check
export QT_QPA_PLATFORM=offscreen
%pytest -q tests/unit


%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/web-app-launcher
%{_datadir}/applications/com.nikromen.WebAppLauncher.desktop
%{_datadir}/metainfo/com.nikromen.WebAppLauncher.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/com.nikromen.WebAppLauncher.svg


%changelog
%autochangelog
