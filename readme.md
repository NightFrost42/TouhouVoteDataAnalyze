# 车万人气数据分析
- fun.xlsx是中日名称对照表，因为用的程序有点多，不好改名，暂时不管

1. `TouhouVote.py`将中日的投票数据分别进行分组，使用对照表中的数据为其添加首次出现作品信息，并去掉旧作和仅书籍出场角色的信息
2. `top7.py`、`top15.py`、`top30.py`分别查看对应的前n名角色的票数占总票数的百分比（仅日区数据）
3. `GroupAnalyze_jp.py`可以查看各个作品的投票占比的变化趋势
4. `CharacterAnalyze_jp.py`和`CharacterAnalyze_cn.py`分别查看对应角色的得票比例在各自大区的变化趋势
5. `difference.py`可以比较中日人气投票数占比
6. `CharacterTagAnalyze-tfidf.py`、`CharacterTagAnalyze-freq.py`、`CharacterTagAnalyze-textrank.py`、`CharacterTagAnalyze-LDA.py`分别是不同方法，在thbwiki上提取出的角色关键词
7. `CharacterTagAnalyze-clusters.py`为所有四种方法的关键词聚合分析
8. `人气拉表统计.opju`为origin作图的人气数据
9. `TagGetMoeWiki.py`获取萌娘百科中角色萌点作为tag