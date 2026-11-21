# 워크스테이션 듀얼 부트: 루트 원격 축소와 BMC 가상 미디어로 Windows 11 설치

2026-11-21. 리눅스 루트(980 PRO 2 TB) 하나뿐이던 디스크를 리눅스 500 GiB와 Windows 약 1.36 TiB로 나눴다. 손이 간 것은 모니터와 Windows 설치 화면뿐이고, 나머지는 원격(Spark와 Mac)에서 했다. 다음에 같은 일을 할 때 이 순서대로 하면 된다. 스크립트는 [`configs/ws-dualboot/`](../configs/ws-dualboot/)에 있다.

## 1. 루트를 비운다 (재부팅 없음)

ext4 루트는 마운트된 채로 줄일 수 없다. 줄이는 동안 옮길 바이트가 적을수록 오프라인 시간이 짧다. 1.4 TB를 쓰던 루트를 401 GB까지 비웠다.

- 끝난 작업 트리를 지웠다(빌드 사본이라 코드는 Mac 쪽 브랜치에 있다).
- 큰 디렉터리를 `/models`(nvme0)와 `/data`(HDD)로 옮기고 같은 경로에 bind mount로 붙였다. fstab 줄에는 `nofail,x-systemd.requires-mounts-for=/models`를 단다. `nofail`이 없으면 `/models`가 늦게 오거나 fsck에 걸릴 때 부팅이 emergency 모드에 빠진다.
- 모델 파일은 bind가 아니라 새 전체 경로로 옮기고 참조를 고친다(심링크 금지 규칙).

**틀렸던 것.** nvme0에 약 500 GB를 쉬지 않고 rsync로 쓰다가 드라이브가 버스에서 떨어졌다(쓰기 timeout → 컨트롤러 reset 실패 → `Disabling device`, ext4 journal abort). 10-23, 11-06에 이어 세 번째다. 연속 대용량 쓰기에서만 나고 재부팅하면 정상으로 돌아온다(journal 재생, fsck 불필요, SMART media error 0). 다음에는 `rsync --bwlimit`로 속도를 제한하거나 끊어서 쓴다.

## 2. 루트를 원격으로 축소한다 (재부팅 한 번)

라이브 USB 없이, initramfs 안에서 루트를 마운트하기 전에 돌린다.

1. 백업: `/etc`, `/root`의 설정 파일, `sfdisk -d`, fstab, GRUB 설정을 HDD에 받아 둔다.
2. 드라이런: `echo ", <섹터>" | sfdisk --no-act -N 2 <디스크>`로 시작 위치는 그대로이고 크기만 바뀌는지 본다.
3. initramfs 훅(`initramfs-hook-shrinkroot`)으로 e2fsck, resize2fs, sfdisk, dumpe2fs를 넣는다. `local-premount-shrinkroot`는 커널 줄에 `shrinkroot=1`이 있을 때만 돈다. 순서는 e2fsck → resize2fs로 490 G까지 축소 → 파일시스템이 새 파티션보다 작은지 확인 → sfdisk로 p2를 500 GiB로 → 파티션까지 resize2fs로 다시 키움 → e2fsck다. 앞 단계가 실패하면 파티션을 건드리지 않고 부팅을 계속한다. UUID 확인에는 `dumpe2fs -h`를 쓴다. busybox `blkid`는 `-o value`를 모른다.
4. GRUB: `GRUB_DEFAULT=saved`로 두고, `40_custom`에 `shrinkroot` 항목을 추가하고(`grub-40_custom-shrinkroot`), `grub-set-default 0` 다음 `grub-reboot shrinkroot`을 한다. 다음 한 번만 그 항목으로 부팅한다.
5. 재부팅 전에 BMC 가상 CD를 뗀다. 펌웨어가 CD를 먼저 부팅하면 Windows 설치기의 "아무 키나 누르세요" 창에 걸린다.
6. 결과는 initramfs가 `/run/shrinkroot.log`에 남긴다(`/run`이 실제 시스템으로 넘어온다).

## 3. BMC를 되살린다

ASUS ASMB9-iKVM(AMI MegaRAC SP-X, 펌웨어 1.17)이 LAN에서 사라져 있었다. 고정 주소를 줘도 응답이 없어 케이블이 빠졌다고 의심했지만, 원인은 멈춘 BMC였다. 호스트에서 `ipmitool lan set 1 ipsrc dhcp`와 `ipmitool mc reset cold`를 하자 약 3분 뒤 DHCP로 올라왔다. 다음부터는 먼저 `ip neigh`에서 BMC MAC을 찾고, 없으면 cold reset을 한다.

웹 비밀번호를 몰라도 호스트 안에서 IPMI로 임시 관리 계정을 만들 수 있다: `ipmitool user set name 3 …`, `user set password 3 … 16`, `channel setaccess 1 3 … privilege=4`, `user enable 3`. 이 계정은 웹 API(`/api/session`)에는 들어가지만 **Redfish는 401**이다. 그래서 가상 미디어는 웹 UI가 쓰는 API로 붙인다(`bmc-api.sh`). 설치가 끝나면 계정을 지운다. 기본 계정의 비밀번호를 여러 번 틀려 잠그지 않도록, 추측은 한 번만 한다.

## 4. Spark에서 ISO를 서빙하고 가상 CD로 붙인다

- **ISO 링크**: Microsoft 다운로드 API는 스크립트 요청에 `ErrorSettings.SentinelReject`를 돌려준다(세션 태그를 먼저 보내도 같다). 실제 브라우저 세션에서 "64-bit 다운로드" 버튼의 href만 받는다. 링크는 24시간 살아 있다. 같은 페이지의 "다운로드 확인" 표가 SHA256 기준이다. Windows 11 26H2 한국어 x64가 맞았다.
- **Samba**: 공유 하나를 읽기 전용으로 열고, LAN과 직결 링크에만 bind한다. 펌웨어가 오래되어 `server min protocol = NT1`과 `ntlm auth = yes`가 필요했다. guest 접속은 `map to guest = Bad User`를 줘도 BMC가 보내는 사용자 이름 때문에 `NT_STATUS_NO_SUCH_USER`로 막혔다. 전용 Samba 사용자를 하나 만들어 해결했다.
- **붙이는 순서** (`bmc-api.sh`):
  1. `GET /api/settings/media/general`의 결과에서 `remote_media_support=1`, `mount_cd=1`, `cd_remote_server_address`, `cd_remote_source_path=/<공유>`, `cd_remote_share_type=cifs`, 사용자와 비밀번호를 바꿔 `PUT`한다. "Remote Media Misc Configuration" 오류(16425, HTTP 500)가 나도 CD 쪽 값은 저장된다. 비어 있는 HD 칸 때문으로 보인다.
  2. `GET /api/settings/media/remote/images`에 ISO 이름이 나오면 공유 접속은 된 것이다.
  3. `POST /api/settings/media/remote/start-media`에 **본문** `{"image_name":…,"image_type":1,"image_redirection":1,"image_index":0}`을 보낸다. 쿼리 문자열로 보내면 13410 오류다. 정확한 본문은 BMC의 `/source.min.js`에서 찾았다.
  4. 호스트 `dmesg`에 `AMI Virtual CDROM0`이 뜨면 붙은 것이다. 떼기는 같은 본문으로 `stop-media`다.
- Mac에서는 LAN 장비에 직접 닿지 않는다. BMC 웹 UI를 보려면 `ssh -N -L 8443:<bmc>:443 <spark>`를 열고 `https://localhost:8443`으로 들어간다.

## 5. 설치와 정리

설치 화면에서는 nvme1의 "할당되지 않은 공간"만 고르고, 4 TB(`/models`)와 18 TB(`/data`) 디스크는 고르지 않는다. EFI 파티션은 같이 쓴다. 설치가 끝나면 다음을 한다.

- GRUB에 Windows 항목을 추가하고 timeout을 늘린다. 기본 부팅은 리눅스로 둔다.
- 임시 BMC 계정과 Samba 사용자를 지우고, SMB1 설정과 smbd를 원래대로 되돌린다.

결과(축소 시간, 설치 결과)는 이 절 아래에 잰 대로 적는다.
