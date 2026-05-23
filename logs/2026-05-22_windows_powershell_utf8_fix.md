# Windows 10 Codex PowerShell 한글 인코딩 문제를 UTF-8 기본값으로 고정한 작업 로그.

## 원인 확인

- `cmd` 코드 페이지가 `949`였습니다.
- PowerShell 세션은 `OutputEncoding=utf-8`, `InputEncoding=ks_c_5601-1987`로 섞여 있었습니다.
- Codex 내부 PowerShell은 `CurrentUserCurrentHost` 프로필을 일반 `Documents`가 아니라 세션별 sandbox 경로에서 찾는 경우가 있었습니다.

## 적용한 조치

- 아래 UTF-8 고정 설정을 PowerShell 프로필에 반영했습니다.

```powershell
[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
chcp 65001 > $null
$PSDefaultParameterValues['*:Encoding'] = 'utf8'
$env:PYTHONIOENCODING = 'utf-8'
```

- 수정 경로
  - `C:\Users\leedh\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`
  - `C:\Windows\System32\WindowsPowerShell\v1.0\Microsoft.PowerShell_profile.ps1`
  - `C:\Windows\System32\WindowsPowerShell\v1.0\profile.ps1`
  - `C:\Users\CodexSandboxOffline\.codex\.sandbox\cwd\ceac44d435f98bd\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`

## 검증

- 새 PowerShell 세션에서 아래 상태를 확인했습니다.
  - `OutputEncoding = utf-8`
  - `InputEncoding = utf-8`
  - `Active code page: 65001`

## 메모

- Codex sandbox 경로는 세션마다 달라질 수 있습니다.
- 다만 절대경로인 `AllUsersCurrentHost`, `AllUsersAllHosts` 프로필도 함께 맞춰 두어서 이후 세션에서도 UTF-8이 유지될 가능성이 높습니다.
