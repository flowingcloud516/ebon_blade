# File Transfer Connector 设计

状态：第一期暂不实现

最近更新：2026-10-27

第一期二进制版本管理改为使用普通Linux主机的SSH/SFTP能力，直接复用现有`ssh_connector`，并将下载结果保存在当前工作空间的`versions/`目录。因此暂不实现独立FTP Connector，也不要求Linux部署FTP服务。

当前最小方案见[简单二进制版本目录设计](../../../design/artifact-version-management.md)。如果以后出现必须使用FTP/FTPS而SSH不可用的服务器，再根据真实环境补充本Connector。
