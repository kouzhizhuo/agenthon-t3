Executive summary: This prepared workflow first checks package upload scope in a lightweight job before downloading the payload or starting full verification. Verification then has only contents-read permission and saves the selected Docker image, immutable config ID, archive SHA-256 and complete selection receipts. Publication has package-write permission, reuses a successful verification artifact without rebuilding, checks upload scope again and always removes its private Docker credentials. Anonymous proof hashes the remote manifest, config and every layer without using the Docker daemon cache. No workflow was uploaded or dispatched, and no competition submission was made.

本流程只解决失败后重复验证的问题，不把镜像发布当成比赛提交，也不证明230000。当前版本没有足够阈值证据，不能自动新增正式提交。`controller.py` 的默认行为是 plan-only，`--execute` 才执行 archive/registry操作。

验证job运行既有 build/import controls/full71/pilot/select；最后 `docker image save` 精确 immutable selected ID，保存 `selected-image.tar`。只保存一个 image，archive内config字节的sha256必须就是被测ID，每个layer都存在且为regularfile，并流式校验uncompressedlayer字节hash与config.rootfs.diff_ids一致。`BUNDLE.json`绑定archive大小/hash、full/pilot/selector文件hash与run/commit身份。publish消费侧再次检查selected/verification/archive/image ID关系、boundSELECTEDreceipt、finalmarker及finalreceipts，校验调用时固定BUNDLEhash，load后再次inspect精确ID。失败重跑publishjob，或者新dispatch用旧successfulverificationrunartifact，都不重build或rerun42分钟验证。

package scope预检不是login。controller请求只限本repository的pull,push token，然后nonce标记空POST `/v2/kouzhizhuo/agenthon-t3/blobs/uploads/`。只有202才继续；未提交digest、未PUT、未创建manifest/tag/version。收到Location后验证https/samehost/samerepository且非root，再对**确切返回Location含原query**发DELETE；仅204认定会话清理成功。controller不改package权限、不使用PAT、不给别的repo授权。nonce与Location的hash保留，Location本身与token不写日志。

Opus建议删除daemon image以证明匿名下载存在额外破坏性且没有必要，本实现没有采用。无凭据HTTP token只请求pull scope，fetch immutable manifest并sha256验证，随后流式读取config与所有压缩layer，每项严格size/digest检查。CDN redirect仅https，无Authorization转发，返回数据由hash验证；不保存signedURL。这样远程读取不能由daemon缓存满足，且不会删除被测镜像。结果包括remoteconfigdigest与testedimageID相等证明；不公开完整Config.Env。

publish独立私有 DOCKER_CONFIG 在 RUNNER_TEMP 中mode700，token通过stdin传给docker login并从其child环境去除；try/finally无论scope/login/tag/push/proof失败都logout并删除私有目录，保存非敏感cleanup/status receipt。证据只上传publish output目录，不能上传RUNNER_TEMP或完整Docker config。

支持已验证docs-only最终层：archive接受 `--final-dir`，要求真实 `FINAL_IMAGE_RESULT.json` 的prepared/strictsmoke/freeze证明，以及freeze的selectedID到finalID关系。strict nproc=256/fsize=268435456必须在final证据通过。最终archive保存**finalID**，而不是原selectedID，并绑定最终receipt；发布不重新构建文档层。若docs-layer还未构建验证，就只能保留研发镜像artifact，不能声明最终许可分发已通过。现有finalcontroller需在独立job或verify结束前实际运行后才能用此模式。

最小workflow提供三种模式：`preflight-only`仅空scopeprobe+DELETE会话，`verify`验证完整payload，或`publish-only`指定本仓库旧runartifact及其BUNDLEsha256。preflight-only显式跳过verify和publish，不需要payload/runID/bundlehash，不materialize、不load/push镜像。token packagewrite只给轻量preflightjob和publishjob；verifyjob保持contentsread。preflight稀疏checkout只取publication控制器，不materialize、不download image/payload、不安装依赖、不运行Docker；verify显式needs preflight成功。publish-only也先检查scope。公开artifact必须保留完整raw receipts且不能包含teamkey。workflow本身不制作submissionZIP、不消耗CodaBench次数。

有限测试使用假的Registry响应和Docker子进程，测试恶意Location/跨host、scope拒绝、DELETE原query、tamperedarchive、remoteblobhash/size/redirectauth以及失败credentialcleanup。未进行任何实际registry写探针。

执行注意：minimalworkflow要求仓库包含 `completion1009/publication_v2/` 控制器及相同路径的 reviewed `WORKFLOW_PAYLOAD.tar.xz`；旧内嵌workflow不能直接当新复用workflow使用。此前失败run没有docker-save archive，因此不能凭现有evidence恢复那个daemonimage；新workflow只有在verify成功并上传archive之后才具备单独重publish能力。30天retention可延长证据窗口，但本地仍应保留下载原件与hash。GitHub `Re-run failed jobs` 会只重publish失败job，publish-only模式还需提供先前BUNDLE.json SHA256与本仓库runID。

本次有限控制包括controller、materialize、finalreceipt接口及workflow结构；结果与exact sourcehash见 `EVIDENCE_MANIFEST.json`。初次有1项因断言把普通词“nonsecret”匹配为credential失败，已将status文案改为“retained process/receipt status”后通过，未涉及token或network。

具体上传布局由 `prepare_upload.py --out <new-directory>` 生成，archive只含5个明确成员：

- `.github/workflows/t3-publication-v2.yml`
- `completion1009/publication_v2/controller.py`
- `completion1009/publication_v2/materialize.py`
- `completion1009/publication_v2/README.md`
- `completion1009/WORKFLOW_PAYLOAD.tar.xz`

当前远程repository只有embeddedworkflow，以上4个控制文件与payload路径都需真实上传才可运行；只复制YAML会失败。生成器在本地完整解压payload并对73个member与原manifest核验，保存每个上传member的bytes/hash及tarhash到UPLOAD_MANIFEST。上传root必须为repository/的内容，不能多包一层publication_v2目录；AppleDouble和cache文件不在archive成员列表。

此准备包沿用已评测的旧payload以验证发布机制，**不含lazy候选、nproc/fsize修正或自有LICENSE层**；它不是230000候选，也不是合规最终提交包。`controller.py archive --final-dir <verified-final-directory>` 接口按现有 `prepare_final_image.py` 的`t3-final-doc-layer-result-v1`和freeze schema检查，要求exacttwo-docpaths/config相同以及strictlimits；现有preparefinal必须先有publishedreference，因此本最小workflow没有谎称在firstpublish前完成final。未来真正final流程需先验证性能阈值、按本地最终层控制准备/验证finalID，再重新archive它并发布；不得把原savedID当finalID。

运行顺序：先独立`mode=preflight-only`一次，确认实际scopeprobe202及DELETE204，不需要运行长验证。随后verify dispatch输入UPLOAD_MANIFEST中的`mode=verify`及`payload_sha256`，只有新的preflight成功才开始完整verification。成功后记录artifact `t3-verified-image-bundle-v2`中的BUNDLE.json sha256。publish失败时优先GitHub Re-run failed jobs；若单独dispatch，输入`mode=publish-only`、原verificationrunID与BUNDLEsha256。两者都load被测archive，不重build。preflight失败时先排查scopepermissions事实，本工具不会修改package权限。此文只说明runnable流程，本次未dispatch。
