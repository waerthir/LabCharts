### 数据

数据集在`data\download\cloud_items`下，对应的索引源文件是`data\ref\selected_manifest.json`

我自己选用数据的时候选用的是`data\download\cloud_items`下每个子项目的 json 里面的`ready3_open_rewrite.resolved_question_text`

### 词云流程

词云分为三个独立步骤：统计题干词频、过滤无意义词、生成词云图片。题干字段只读取`ready3_open_rewrite.resolved_question_text`。

#### 1. 统计词频

运行`src/count_word_frequency.py`。脚本根据 manifest 中每项的`item_path`，结合远程共同前缀和本地下载目录，找到已下载的题目 JSON 并统计词频。

```powershell
E:\TrashE\Miniconda3\envs\dag_env\python.exe src/count_word_frequency.py `
--manifest data/ref/selected_manifest.json `
--local-root data/download/cloud_items `
--remote-prefix /home/lijingyue/LiangEnRui `
--output-dir data/output/word_frequency `
--min-length 3
```

输出目录中会生成：

- `word_freq.csv`：词频主文件，字段为`rank`、`word`、`count`、`doc_count`。
- `extraction_report.csv`：每道题的提取状态，例如成功、缺失文件、题干字段为空。
- `summary.json`：总体统计结果。

`count`表示词在全部题干中的出现总次数；`doc_count`表示包含该词的题目数量。`--min-length 3`会忽略少于 3 个字符的词。

#### 2. 过滤无意义词

先创建剔除词文件，例如`data/ref/remove_words.txt`。每行一个词；空行和以`#`开头的行会被忽略。

```text
figure
diagram
image
image1
line
find
abcd
```

运行`src/filter_word_frequency.py`，删除指定词并按`count`重新排序、重新生成`rank`。

```powershell
E:\TrashE\Miniconda3\envs\dag_env\python.exe src/filter_word_frequency.py `
--input-csv data/output/word_frequency/word_freq.csv `
--output-csv data/output/word_frequency/word_freq_filtered.csv `
--remove-words-file data/ref/remove_words.txt
```

也可通过`--remove-words`临时补充逗号分隔的剔除词：

```powershell
E:\TrashE\Miniconda3\envs\dag_env\python.exe src/filter_word_frequency.py `
--input-csv data/output/word_frequency/word_freq.csv `
--output-csv data/output/word_frequency/word_freq_filtered.csv `
--remove-words-file data/ref/remove_words.txt `
--remove-words figure,diagram,image
```

该步骤只按词表中的文本完全匹配删除词，不会再次改变大小写或空格。

#### 3. 生成词云

首次使用前安装依赖：

```powershell
conda install -n dag_env -c conda-forge wordcloud
```

使用过滤后的词频 CSV 生成词云：

```powershell
E:\TrashE\Miniconda3\envs\dag_env\python.exe src/make_word_cloud.py `
--input-csv data/output/word_frequency/word_freq_filtered.csv `
--output-image data/output/word_cloud/word_cloud.png `
--weight-column count `
--max-words 180 `
--width 1800 `
--height 1100 `
--background-color white `
--colormap viridis `
--random-state 42 `
--prefer-horizontal 0.9 `
--font-path "C:\Windows\Fonts\times.ttf"
```

参数说明：

- `--weight-column count`：按总出现次数决定字体大小，当前默认建议使用该参数。改为`doc_count`时，按出现该词的题目数量决定字体大小。
- `--max-words 180`：只使用词频最高的 180 个词，可根据图片密度调整。
- `--width`、`--height`：输出图片的像素尺寸。
- `--background-color`：背景色。
- `--colormap`：颜色方案，例如`viridis`、`Blues`、`GnBu`、`YlGnBu`、`cividis`。
- `--random-state 42`：固定词云布局；相同输入和参数下可得到相同布局。
- `--prefer-horizontal 0.9`：控制横向词的比例；`1.0`表示全部横向。
- `--font-path`：字体文件路径。英文词云可以省略；指定字体路径后，输出字体风格更稳定。
