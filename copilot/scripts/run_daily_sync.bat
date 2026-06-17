@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
cd /d "%PROJECT_DIR%"

echo [%date% %time%] 开始同步钉钉媒体数据...
python "%PROJECT_DIR%\scripts\sync_dingtalk_media.py" --update-db --output "%PROJECT_DIR%\data\dingtalk_media_report_daily.json"
python "%PROJECT_DIR%\scripts\sync_dingtalk_activity_rules.py" --apply --output "%PROJECT_DIR%\reports\dingtalk_activity_rules_daily.json"
python "%PROJECT_DIR%\scripts\sync_dingtalk_product_detail_assets.py" --apply --auto-approve-low-risk --output "%PROJECT_DIR%\reports\dingtalk_product_detail_assets_daily.json"
python "%PROJECT_DIR%\scripts\audit_dingtalk_product_details.py" --output "%PROJECT_DIR%\reports\dingtalk_product_detail_audit_daily.json"
echo [%date% %time%] 同步完成，报告已保存到 data\dingtalk_media_report_daily.json
echo.
