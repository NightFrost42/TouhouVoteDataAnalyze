/**
 * Charts and other
 */
var chart = {};
var paperoption = [];
var geomax = [];
var option = [];

$(document).ready(function(){
	var itemDiv = $('#graph-div');
	var itemChart = $('#graph-chart');
	
	var chart;
	chart = echarts.init(itemChart[0]);
	
	$.post('api.php?action=make&object=votecrossvote&text='+type+'&filter='+number+'&rate='+filter).done(function (data) {
		//console.log(data);
		
		var categories = [];
		data.categories.forEach(function (item, i) {
			categories[i] = {
				name: item
			};
		});
		//console.log(data.categories);
		data.data.forEach(function (node) {
			node.symbolSize /= 4;
			node.draggable = true;
			node.label = {
				normal: {
					show: node.symbolSize >= 10
				}
			};
			//node.tooltip = {
			//};
		});
		data.links.forEach(function (link) {
			var width = link.lineWidth;
			width = (width > 18) ? width = 18 : ((width < 1) ? 1 : width );
			link.lineStyle = {
				width: width
			};
			link.emphasis = {
				lineStyle: {
					width: (width * 1.1 > 20) ? 20 : width * 1.1
				}
			};
		});
		option = {
			title : {
				text: sitetitle + '同投可视化（'+typeWord+'部分前' + number + '名）',
				show: false
			},
			tooltip: {},
			legend: [{
				data: data.categories
			}],
			animationDuration: 1500,
			animationEasingUpdate: 'quinticInOut',
			toolbox: {
				show: true,
				top: 'bottom',
				feature: {
					saveAsImage: {
						type: ['png']
					},
					restore: {}
				}
			},
			series : [
				{
					name: '同投可视化',
					type: 'graph',
					layout: 'force',
					force: {
						//initLayout: 'circular',
						gravity: 0.23,
						repulsion: 1200,
						edgeLength: [3, 350]
					},
					data: data.data,
					links: data.links,
					categories: categories,
					roam: true,
					focusNodeAdjacency: true,
					itemStyle: {
						normal: {
							borderColor: '#fff',
							borderWidth: 1,
							shadowBlur: 10,
							shadowColor: 'rgba(0, 0, 0, 0.3)'
						}
					},
					label: {
						position: 'right',
						//formatter: '{b}'
					},
					lineStyle: {
						color: 'source',
						curveness: 0.1
					},
					edgeLabel: {
						//formatter: '{@source} > {@target} : aaaa'
					},
					tooltip: {
						formatter: function(params) {
							var labelWord = '';
							if (params.dataType == 'node') {
								labelWord = params.name+
									'<br />总票数：' + params.value +
									'<br />初登场：' + categories[params.data.category].name;
							} else if (params.dataType == 'edge') {
								labelWord = params.data.sourceName+'<>'+params.data.targetName+
									'<br />卡方值：' + params.data.valueShow +
									'<br />同投值：' + params.data.line + '%' +
									'<br />相关值：' + params.data.test + '<br />' +
									'<br />' + params.data.sourceName + '票数：' + params.data.sourceVote +
									'<br />' + params.data.targetName + '票数：' + params.data.targetVote +
									'<br />同投票数：' + params.data.crossVote + '<br />' +
									'<br />线条粗细：' + params.data.lineWidth +
									'<br />吸引力值：' + Math.round(params.value * 10000) / 10000 +
									'<br />基准距离：' + Math.round(1 / params.value * 10000) / 10 * 2;
							} else {
								return '';
							}
							
							return labelWord;
						}
					},
					emphasis: {
						lineStyle: {
							//width: 10
						}
					}
				}
			]
		};

		console.log(option);
		
		chart.setOption(option);
		chart.resize();
	});
		
	
	$(window).resize(function() {
		chart.resize();
	});
	
});