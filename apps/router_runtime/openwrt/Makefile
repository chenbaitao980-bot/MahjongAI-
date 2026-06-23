# OpenWrt SDK Makefile — mahjong-mitm
#
# 官方 SDK 打包路径（与 build_ipk.sh 二选一；build_ipk.sh 无需 SDK，推荐先用它）。
#
# 用法:
#   1. 下载对应 SDK（GL-MT3000 = mediatek/filogic, OpenWrt 23.05）
#   2. ln -s $(pwd)/apps/router_runtime <SDK>/package/mahjong-mitm
#      （或把本目录拷进 SDK 的 package/ 下）
#   3. cd <SDK> && make package/mahjong-mitm/compile V=s
#   产物: <SDK>/bin/packages/<arch>/base/mahjong-mitm_*.ipk

include $(TOPDIR)/rules.mk

PKG_NAME:=mahjong-mitm
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_MAINTAINER:=mahjong-ai

include $(INCLUDE_DIR)/package.mk

define Package/mahjong-mitm
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Setup-period hotfix MITM
  DEPENDS:=+python3-light +python3-urllib +python3-openssl +kmod-nft-nat
  PKGARCH:=all
endef

define Package/mahjong-mitm/description
  Phone connects router WiFi, hotfix rewrites NetConf to point at ECS, then phone
  roams to any network. Router does not touch 7777 game traffic afterwards.
endef

# 无源码编译：纯 Python + 数据文件
define Build/Compile
endef

define Package/mahjong-mitm/install
	$(INSTALL_DIR) $(1)/usr/lib/$(PKG_NAME)/mahjong_mitm
	$(INSTALL_DATA) ./mahjong_mitm/*.py $(1)/usr/lib/$(PKG_NAME)/mahjong_mitm/
	$(INSTALL_DIR) $(1)/usr/lib/$(PKG_NAME)/assets
	$(INSTALL_DATA) ./assets/game_base.apk $(1)/usr/lib/$(PKG_NAME)/assets/
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./openwrt/files/etc/init.d/$(PKG_NAME) $(1)/etc/init.d/$(PKG_NAME)
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./openwrt/files/etc/config/$(PKG_NAME) $(1)/etc/config/$(PKG_NAME)
	$(INSTALL_DIR) $(1)/etc/nftables.d
	$(INSTALL_DATA) ./openwrt/files/etc/nftables.d/99-$(PKG_NAME).nft $(1)/etc/nftables.d/99-$(PKG_NAME).nft
endef

define Package/mahjong-mitm/postinst
#!/bin/sh
$(INSTALL_DIR)
[ -n "$${IPKG_INSTROOT}" ] && exit 0
CERT_DIR="/usr/lib/mahjong-mitm/data/mitm"
mkdir -p "$$CERT_DIR"
if [ ! -f "$$CERT_DIR/mitm_cert.pem" ]; then
	openssl req -x509 -newkey rsa:2048 -nodes \
		-keyout "$$CERT_DIR/mitm_key.pem" -out "$$CERT_DIR/mitm_cert.pem" \
		-days 3650 -subj "/CN=gxb.hzxuanming.com" >/dev/null 2>&1
fi
/etc/init.d/mahjong-mitm enable
/etc/init.d/mahjong-mitm start
exit 0
endef

$(eval $(call BuildPackage,mahjong-mitm))
