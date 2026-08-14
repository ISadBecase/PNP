<div align="center">
  <img src="./assets/logo.png" width="128">

  <h1>Paper2Poster</h1>

  <p>
    <a href="./README.en.md">English</a>
    |
    <a href="./README.md">简体中文</a>
  </p>

</div>


## 1️⃣ 海报样例（2026.08.10）

<table>
  <tr>
    <td align="center">
      <img src="./assets/example3.png" width="200" alt="修改结果"><br>
      <b>arXiv.2506.18028</b>
    </td>
    <td align="center">
      <img src="./assets/example2.png" width="200" alt="审查结果"><br>
      <b>arXiv.2602.19083</b>
    </td>
    <td align="center">
      <img src="./assets/example4.png" width="200" alt="最终结果"><br>
      <b>arXiv.2306.00978</b>
    </td>
    <td align="center">
      <img src="./assets/example1.png" width="200" alt="生成结果"><br>
      <b>arXiv.2211.10438</b>
    </td>
  </tr>
</table>


## 2️⃣ 简介

本项目为一个Paper2Poster项目，旨在借助智能体(Agent)将学术论文(Paper)转换为学术海报(Poster),基本无需人工介入，支持Latex格式二次编辑。

> [!NOTE]
>
> 项目需长期更新中，请等待 ✒️✒️✒️...
>
> 若有相关问题或建议，可参考5️⃣ FAQ,其余问题请移步Issue 🤗🤗🤗...

## 3️⃣ 环境

### Windows

- 📦 Python 相关包

	```Shell
	Set-Location D:\kao\PNP

	conda create -n PNP python=3.11 pip -y
	conda activate PNP
	python -m pip install -r .\requirements.txt
	```

- 💻 系统依赖

    安装以下工具，并将其加入 `System PATH`：

    - **TeX Live**
    - **pdftocairo**

- 运行示例

    - ```shell
        & "D:\Anaconda3\envs\Pytorch\python.exe" .\code\entry.py 2402.17228
        ```

    - ```shell
        & "D:\Anaconda3\envs\Pytorch\python.exe" .\code\entry.py 2402.17228 2508.10104 2312.00752
        ```
> [!TIP]
>
> 如果您生成海报后认为其效果并不理想，可自由编辑 output/poster/<paper_id>/ 内的Latex文件，进行个性化的二次编辑。
>
> 实际上，您可以在entry.py中学习配置相关参数，以从项目运行过程中的任意阶段编辑后断点运行，逐步完善最终海报效果！🤗🤗🤗

## 4️⃣ 文件树

- Input file

  ```python
  PNP/
  ├── .gitignore
  ├── README.md                         # 中文默认文档
  ├── README.en.md                      # 英文文档
  ├── LICENSE                           # MIT许可证
  ├── requirements.txt
  │
  ├── assets/
  │   ├── logo.png                         # 项目Logo
  │   ├── example1.png                     # README海报样例
  │   ├── example2.png
  │   ├── example3.png
  │   └── example4.png
  │
  └── code/
      ├── entry.py                         # 项目运行入口
      │
      ├── agent/
      │   ├── __init__.py
      │   ├── paper_classifier.py          # 负责论文贡献类型判断
      │   ├── paper_elements.py            # 负责二次提取 Section、Figure、Table、Equation元素
      │   ├── parser_arxiv.py              # 负责将Table、Equation的LaTeX片段及Figure PDF转图片
      │   ├── parser_vlm.py                # 负责Figure、Table、Equation元素的VLM分析
      │   ├── rag.py                       # 负责LightRAG建库与查询
      │   ├── response.py                  # 负责容错LLM返回的JSON格式
      │   ├── summary.py                   # 负责汇总文本内容与视觉资源
      │   ├── poster_layout.py             # 负责海报Panel分组、双栏布局及资源尺寸计算
      │   ├── poster_latex.py              # 负责LaTeX模板渲染与海报编译
      │   └── poster_review.py             # 海报栏与最终海报VLM审查
      │
      ├── config/
      │   └── poster_layout.yaml            # 海报尺寸、字体、间距及布局参数（需要结合实际微调）
      │
      ├── prompt/
      │   ├── zh_en.json                    # 中文Prompt文件的哈希记录，自动化中英Prompt互译
      │   │
      │   ├── zh/
      │   │   ├── paper_classifier.yaml		    # 用于判断论文贡献类型
      │   │   ├── paper_type_guidance.yaml	    # 用于辅助总结论文内容，因论文贡献类型而异
      │   │   ├── equation_analyzer.yaml		# 用于公式VLM分析
      │   │   ├── figure_analyzer.yaml		    # 用于图像VLM分析（可选）
      │   │   ├── table_analyzer.yaml			# 用于表格VLM分析（可选）
      │   │   ├── rag_queries.yaml			    # 用于RAG Query
      │   │   ├── rag_type_queries.yaml		    # 用于辅助RAG Query，因论文贡献类型而异
      │   │   ├── rag_asset_analyzer.yaml		# 用于筛选有价值的Figure、Table、Equation元素
      │   │   ├── summary.yaml				    # 用于RAG Query后的二次内容梳理
      │   │   ├── summary_type_guidance.yaml	# 用于辅助RAG Query后的二次内容梳理，因论文贡献类型而异
      │   │   ├── poster_column_review.yaml	    # 用于VLM审理海报左右栏效果
      │   │   └── poster_final_review.yaml	    # 用于VLM审理最终海报效果
      │   │
      │   └── en/							# 与上述 zh/ 内同名Prompt同理，仅英汉互译
      │       ├── paper_classifier.yaml
      │       ├── paper_type_guidance.yaml
      │       ├── equation_analyzer.yaml
      │       ├── figure_analyzer.yaml
      │       ├── table_analyzer.yaml
      │       ├── rag_queries.yaml
      │       ├── rag_type_queries.yaml
      │       ├── rag_asset_analyzer.yaml
      │       ├── summary.yaml
      │       ├── summary_type_guidance.yaml
      │       ├── poster_column_review.yaml
      │       └── poster_final_review.yaml
      │
      ├── template/
      │   └── latex/
      │       ├── preamble.tex              # 主题颜色、字体及Panel样式
      │       ├── abstract_measure.tex.j2    # 摘要自然高度测量模板
      │       ├── panel.tex.j2              # 单个Panel模板
      │       ├── column_preview.tex.j2     # 单栏预览模板
      │       └── poster.tex.j2             # 最终海报模板
      │
      ├── utils/
      │   ├── load_env.py                   # 环境变量加载
      │   ├── retry.py                      # API指数退避重试
      │   └── transport_en.py               # 中文Prompt翻译，以哈希规则
      │
      └── arxiv2agent/					  # 详情参考[README Reference]
          ├── __init__.py
          ├── NOTICE.md
          ├── arxiv_api.py                  # arXiv源码下载
          ├── core.py                       # 论文源码解析主流程
          ├── extract.py                    # 内容与资源提取
          ├── _tex.py                       # TeX解析与清理
          ├── bib.py                        # 参考文献处理
          ├── denoise.py                    # 文本降噪
          ├── markers.py                    # 结构标记处理
          ├── schema.py                     # 论文结构定义
          └── writer.py                     # paper.json及资源写出
  ```

- Output file

  ```python
  output/
  ├── run.log                           # 当前一次程序运行日志
  │
  ├── arxiv/						    # 详情参考[README Reference]
  │   └── <paper_id>/
  │       ├── paper.json
  │       ├── source/
  │       ├── figures/
  │       ├── tables/
  │       └── equations/
  │
  ├── temp/
  │   └── <paper_id>/				# 注:输入多个Paper Arxiv ID，则产生多个文件夹
  │       ├── main_section.json		    # 用于论文类型判断的主要章节内容
  │       ├── sections.json			    # 解析出的文本信息
  │       ├── figures.json			    # 解析出的图片信息
  │       ├── tables.json				# 解析出的表格信息
  │       ├── equations.json			# 解析出的公式信息
  │       ├── paper_profile.json		# 论文类型判断信息
  │       ├── content_list.json		    # 结构化论文信息，用于交付RAG
  │       ├── raw_query_results.json	# RAG Query结果记录
  │       ├── summary_input.md		    # RAG Query结果记录(Markdown),用于二次LLM总结
  │       ├── poster_evidence.json	    # 预选海报内容
  │       ├── rag_sections/			    # 可视化各章节整理后的(交付RAG的)内容
  │       ├── rag_storage/			    # LightRAG建库 生成文件
  │       └── poster/
  │           ├── poster_layout.json	    # 当前布局参数
  │           ├── layout_reviews.json	    # 左右栏历次VLM审查结果
  │           ├── iterations/			    # 左右栏迭代历史
  │           │   └── iteration_<n>/
  │           │       ├── left.png
  │           │       ├── right.png
  │           │       ├── layout.json
  │           │       └── review.json
  │           ├── previews/
  │           │   ├── left.png		# 左栏预览图
  │           │   └── right.png		# 右栏预览图
  │           └── latex/
  │               ├── preamble.tex	# LaTeX 导言区模板
  │               ├── panels/			# 海报各panel latex细节
  │               ├── columns/		# 海报栏latex细节
  │               └── measurements/	# 用于计算海报布局
  │
  └── poster/
      └── <paper_id>/
          ├── poster.tex				# 海报最终Latex,可修改
          ├── poster.pdf				# 海报最终PDF
          ├── poster.png				# 海报最终PNG
          ├── poster_review.json		# 最终海报VLM审查结果
          ├── preamble.tex			    # 海报导言区
          ├── panels/					# 海报各Panels Latex
          ├── columns/				    # 海报左右栏 Latex
          └── iterations/
              └── final_<n>/			# 最终海报审查快照
                  ├── poster.pdf
                  ├── poster.png
                  ├── layout.json
                  └── review.json
  ```

## 5️⃣ FAQ

- API配置

  - 项目API可自由在.env配置。
  - 受限于资金和模型效果影响，README中的演示样例的主要使用配置为gpt-4o-mini,text-embedding-3-small,gpt-image-2;由于代码细节，非OPENAI模型暂不支持该项目。
  - ✒️ TODO: 后续将兼容其他厂商的API配置
- 海报效果优化问题

  - 用户可在本项目生成后的Latex版本进行自由修正和编译，以满足个性化需求；
  - 本项目暂不支持横幅效果，不支持画幅尺寸调整；
  - 💡 海报格式布局方面，现有的支持画幅尺寸自定义的项目：有的通过线性模型拟合真实海报布局后再进行VLM微调，比如Paper2Poster；有的直接将画幅尺寸配置交给生图模型进行直接生成，如Paper2Slides。前者由于非直接AI生成，海报分辨率高，但格式单一死板；后者由于采用AI生成，布局自由且合理，视觉效果佳，但受限于模型影响导致海报分辨率较低；若要优化布局方式并保持成本可控的话，我认为应使用智能计算、强化学习等规则类算法，因为海报布局设计具有很多模糊的规则类限制，包括版面大小，文本长度，图片大小、信息间隔等；我并不擅长强化学习、智能算法等知识，故无法深入实践，也许我的判断有误，但当我接触到这个项目时，想到过一个Kaggle竞赛[Santa 2025 - Christmas Tree Packing Challenge](https://www.kaggle.com/competitions/santa-2025)，或许能为布局相关算法提供灵感；
  - 💡 海报内容优化方面，建议修改相关Prompt而非升级模型配置；
  - ✒️ TODO:优化Prompt，提升海报内容质量；
  - ✒️ TODO:创新更佳的自由布局算法，提升画幅的可支配性；
- API费用消耗

  - 在不使用VLM对表格图片资源做辅助分析的情况下，Token消耗费用较少，实际消耗随论文页数、论文配图数量而定；参考默认配置下（gpt-4o-mini,text-embedding-3-small,gpt-image-2），单次单论文运行成本一般 1-2 RMB;
- 项目的一些BUG
  - ✒️ TODO: VLM迭代负反馈存在问题，即需改进多智能体协作部分；
  - ✒️ TODO：当前双栏条件下存在布局不均问题，依赖于布局设计算法和VLM自反馈；
  - ✒️ TODO：生成海报中图片大小不均的问题。
  - 💡 为什么本项目中生成的海报图片呈现大小不均的问题？原始项目如Paper2Poster、Paper2Slides等均参考论文PDF，使用MinerU，Docling等工具将PDF解析为多模态数据后处理，原始PDF内的所有图片使用工具提取后其图片之间的相对比例是确定的，信息密度和面积是对应的合理的；但是本项目PNP是直接读取原始ARXIV TEX解压读取图片资源的，无法(低成本)读取原始latex中对图片的缩放比例，因此导致最终在海报中图片比例失调；同样的情况出现在表格和公式图片中：但为什么不直接使用表格和公式的latex形式呢？因为不同会议论文采用的latex模板大不相同，表格和公式的latex中难免插入宏定义，直接导入容易报错，提升兼容性也非易事，项目的工程化需要时间；
  - ✒️ TODO：本项目还未引入相关Benchmark,待更新；
  - ✒️ TODO：本项目还未在海报引入会议徽标、机构标识等相关代码,待更新；

- 若有其他问题，请移步Issue 🤗🤗🤗


## 6️⃣ 参考
- ☀️ Paper2Poster
  - 🌟 Tool
    - [Arxiv 2 Agent](https://github.com/wuyoscar/arxiv2agent.git)，更多详情见 [RedNote](http://xhslink.cn/o/7ywdm5s2Pbp)
  - 🌟 Agent
    - [Paper2Slides](https://github.com/HKUDS/Paper2Slides)
    - [Paper2Poster](https://github.com/paper2poster/paper2poster)，NeurIPS 2025 Poster
    - [PosterGen](https://github.com/Y-Research-SBU/PosterGen)，CVPR 2026 Findings
    - [PaperX](https://github.com/yutao1024/PaperX)
    - [Paper2Any](https://github.com/OpenDCAI/Paper2Any)
  - 🌟 Skill
    - [Skill2Poster](https://github.com/LEON-gittech/Skill2Poster)
- ☀️ 其他有趣项目
  - [Word Agent](https://github.com/visresearch/WordAgent)
