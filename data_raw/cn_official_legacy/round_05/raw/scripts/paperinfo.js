/**
 * Charts and other
 */
var chart = {};
var paperoption = [];
var geomax = [];
var option = [];

$(document).ready(function(){
	$("#alert-success").hide("slow");
	$("#alert-cross").hide("slow");
	$("#alert-info").hide("slow");
	$("#alert-warning").hide("slow");
	$("#alert-danger").hide("slow");
	$("#cross-change").hide("slow");

	var crossDiv = $('#cross-div');
	var crossChart = $('#cross-chart');
	var crossLoad = $('#cross-load');
	var $crossSelect = [];
	var crossSelect = [];

	$(".cross-select").each(function(i) {
		$crossSelect[i] = $(this).selectize({
			searchField : ['name', 'group'],
			valueField	: 'value',
			labelField	: 'name',
			optgroups   : questgroup,
			optgroupField : 'group',
			options		: questlist,
			lockOptgroupOrder: true,
		});
		crossSelect[i] = $crossSelect[i][0].selectize;
		crossSelect[i].clear();
	});
	
	$('#list').footable({
		"sorting": {
			"enabled": false
		},
		"rows": vote,
		"empty": "暂无数据...",
	});

	$('.container').on('click', '.type-change-row', function(){
		var div = $('#'+$(this).data('div'));
		var now = div.data('now'), other = div.data('other');
		var thischart = $(this).data('chart');
		if (thischart == "progress") {
			if (now == "total") {
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增角色单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增音乐单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增作品单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增组合单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增角色投票人数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增音乐投票人数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增作品投票人数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增组合投票人数'
				});
			} else {
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增角色单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增音乐单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增作品单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendSelect',
					name: '新增组合单项票数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增角色投票人数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增音乐投票人数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增作品投票人数'
				});
				chart['progress'].dispatchAction({
					type: 'legendUnSelect',
					name: '新增组合投票人数'
				});
			}
			div.data({
				'now': other,
				'other': now
			});
			return;
		}
		chart[thischart].setOption(paperoption[thischart][other], true);
		div.data({
			'now': other,
			'other': now
		});
		if (thischart == "geo") {
			if (now == "per") {
				chart['geo'].dispatchAction({
					type: 'legendSelect',
					name: '地区总人数'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '男性数'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '女性数'
				});
			} else {
				chart['geo'].dispatchAction({
					type: 'legendSelect',
					name: '占总体百分比'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '男性占地区百分比'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '女性占地区百分比'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '男性占总体百分比'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '女性占总体百分比'
				});
			}
		}
	});

	$.get('api.php?action=make&object=votedate&text=paper').done(function (data) {
		option = {
				title: {
					text: '投票随时间跨度图表',
					show: false
				},
				tooltip : {
					trigger: 'axis',
					position: function (pt) {
						return [pt[0], '10%'];
					}
				},
				legend: {
					data: data.item.item,
					left: '5%',
					top: 30
				},
				grid: {
					top: 120
				},
				toolbox: {
					show: true,
					feature: {
						dataZoom: {
							yAxisIndex: 'none'
						},
						magicType: {type: ['line', 'bar']},
						restore: {}
					}
				},
				calculable : true,
				xAxis : [
					{
						type: 'category',
						boundaryGap: false,
						data : data.timeline
					}
				],
				yAxis : [
					{
						type : 'value'
					}
				],
				dataZoom: [
						   {
							   type: 'slider',
							   show: true,
							   handleIcon: 'M10.7,11.9v-1.3H9.3v1.3c-4.9,0.3-8.8,4.4-8.8,9.4c0,5,3.9,9.1,8.8,9.4v1.3h1.3v-1.3c4.9-0.3,8.8-4.4,8.8-9.4C19.5,16.3,15.6,12.2,10.7,11.9z M13.3,24.4H6.7V23h6.6V24.4z M13.3,19.6H6.7v-1.4h6.6V19.6z',
							   handleSize: '80%',
							   handleStyle: {
								   color: '#fff',
								   shadowBlur: 3,
								   shadowColor: 'rgba(0, 0, 0, 0.6)',
								   shadowOffsetX: 2,
								   shadowOffsetY: 2
							   }
						   },
						   {
							   type: 'inside',
						   },
						   {
							   type: 'slider',
							   show: true,
							   yAxisIndex: 0,
							   filterMode: 'empty',
							   showDataShadow: false,
							   width: 20,
							   handleIcon: 'M10.7,11.9v-1.3H9.3v1.3c-4.9,0.3-8.8,4.4-8.8,9.4c0,5,3.9,9.1,8.8,9.4v1.3h1.3v-1.3c4.9-0.3,8.8-4.4,8.8-9.4C19.5,16.3,15.6,12.2,10.7,11.9z M13.3,24.4H6.7V23h6.6V24.4z M13.3,19.6H6.7v-1.4h6.6V19.6z',
							   handleSize: '80%',
							   handleStyle: {
								   color: '#fff',
								   shadowBlur: 3,
								   shadowColor: 'rgba(0, 0, 0, 0.6)',
								   shadowOffsetX: 2,
								   shadowOffsetY: 2
							   }
						   }
					   ],
				series : []
			};
		$.each(data.item.list, function(i, item) {
			option.series[i] = {
							name: data.item.item[i],
							type: 'line',
							data: data.data[item]
						};
		});
		chart['progress'] = echarts.init($('#progress-chart')[0]);
		chart['progress'].setOption(option);
		$('#progress-chart').data({'other':'total','now':'vote'});
		chart['progress'].dispatchAction({
			type: 'legendUnSelect',
			name: '新增角色单项票数'
		});
		chart['progress'].dispatchAction({
			type: 'legendUnSelect',
			name: '新增音乐单项票数'
		});
		chart['progress'].dispatchAction({
			type: 'legendUnSelect',
			name: '新增作品单项票数'
		});
		chart['progress'].dispatchAction({
			type: 'legendUnSelect',
			name: '新增组合单项票数'
		});
		chart['progress'].dispatchAction({
			type: 'legendSelect',
			name: '新增角色投票人数'
		});
		chart['progress'].dispatchAction({
			type: 'legendSelect',
			name: '新增音乐投票人数'
		});
		chart['progress'].dispatchAction({
			type: 'legendSelect',
			name: '新增作品投票人数'
		});
		chart['progress'].dispatchAction({
			type: 'legendSelect',
			name: '新增组合投票人数'
		});
	});

	chart['sex'] = echarts.init($('#sex-chart')[0]);
	$.get('api.php?action=make&object=votesex&text=paper').done(function (data) {
		option = []
		option['pie'] = {
				title: {
					text: '问卷图表',
					show: false
				},
				tooltip : {
					trigger: 'item',
					formatter: '{a}<br />{b}: {c}（{d}）'
				},
				legend: {
					show: false
				},
				toolbox: {
					show: false
				},
				color: ['#c23531','#2f4554', '#61a0a8', '#d48265', '#bda29a','#6e7074', '#546570', '#c4ccd3'],
				series : [
							{
								name:'性别',
								type: 'pie',
								radius: ['40%', '60%'],
								selectedMode: 'single',
								label: {
									normal: {
										show: false
									}
								},
								z: 2,
								data:data.data.outside
							},
							{
								name:'年龄',
								type: 'pie',
								radius: [0, '50%'],
								selectedMode: 'single',
								label: {
									normal: {
										show: true,
										position: 'outside'
									}
								},
								labelLine: {
									normal: {
										show: true,
										length: 50,
										position: 'outside'
									}
								},
								z: 3,
								data:data.data.inside
							}
						]
			};
		option["bar"] = {
				title: {
					text: '问卷图表',
					show: false
				},
				tooltip : {
					trigger: 'axis',
					axisPointer : {
						type : 'shadow'
					}
				},
				legend: {
					data: ['男性', '女性', '总数']
				},
				toolbox: {
					show: false
				},
				calculable : true,
				xAxis : [
					{
						type: 'value'
					}
				],
				yAxis : [
					{
						type : 'category',
						data : data.quest.value
					}
				],
				series : [
							{
								name:'男性',
								type: 'bar',
								stack: '总量',
								label: {
									normal: {
										show: true,
										position: 'insideRight'
									}
								},
								data:data.data.male
							},
							{
								name:'女性',
								type: 'bar',
								stack: '总量',
								label: {
									normal: {
										show: true,
										position: 'insideRight'
									}
								},
								data:data.data.female
							},
							{
								name:'总数',
								type: 'bar',
								label: {
									normal: {
										show: true,
										position: 'insideRight'
									}
								},
								data:data.data.all
							}
						]
			};
		paperoption['sex'] = option;
		chart['sex'].setOption(option['pie']);
		$('#sex-chart').data({'other':'bar','now':'pie'});
		chart['sex'].resize();
	});
	
	$.get('./json/china.json', function (chinaJson) {
		echarts.registerMap('china', chinaJson);
	});
	chart['geo'] = echarts.init($('#geo-chart')[0]);
	$.get('api.php?action=make&object=votegeo&text=all').done(function (data) {
		option["all"] = {
				title: {
					text: '投票状态地图',
					show: false
				},
				tooltip : {
					trigger: 'item'
				},
				legend: {
					data: data.leng.all
				},
				visualMap: {
					min: 0,
					max: data.range.all[1],
					itemHeight: 250,
					left: 'left',
					top: 'bottom',
					text: ['多','少'],
					calculable: true,
					inRange: {
						color: ['#F0F8FF', '#6495ED', '#4169E1', '#2A52BE', '#0047AB']
					}
				},
				toolbox: {
					show: true,
					orient: 'vertical',
					left: 'right',
					top: 'center',
					feature: {
						restore: {}
					}
				},
				series : []
			};
		option["per"] = {
				title: {
					text: '投票状态地图',
					show: false
				},
				tooltip : {
					trigger: 'item',
					formatter: '{a}<br>{b}：{c}%'
				},
				legend: {
					data: data.leng.per
				},
				visualMap: {
					min: 0,
					max: data.range.per[1],
					itemHeight: 250,
					left: 'left',
					top: 'bottom',
					text: ['多','少'],
					calculable: true,
					inRange: {
						color: ['#F0F8FF', '#6495ED', '#4169E1', '#2A52BE', '#0047AB']
					}
				},
				toolbox: {
					show: true,
					orient: 'vertical',
					left: 'right',
					top: 'center',
					feature: {
						restore: {}
					}
				},
				series : []
			};
		option["all"].series = [
						{
							name:'地区总人数',
							type: 'map',
							mapType: 'china',
							mapValueCalculation: 'max',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.all
						},
						{
							name:'男性数',
							type: 'map',
							mapType: 'china',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.male
						},
						{
							name:'女性数',
							type: 'map',
							mapType: 'china',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.female
						},
					];
		option["per"].series = [
						{
							name:'占总体百分比',
							type: 'map',
							mapType: 'china',
							mapValueCalculation: 'max',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.per
						},
						{
							name:'男性占地区百分比',
							type: 'map',
							mapType: 'china',
							mapValueCalculation: 'max',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.maleper
						},
						{
							name:'女性占地区百分比',
							type: 'map',
							mapType: 'china',
							mapValueCalculation: 'max',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.femaleper
						},
						{
							name:'男性占总体百分比',
							type: 'map',
							mapType: 'china',
							mapValueCalculation: 'max',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.maleallper
						},
						{
							name:'女性占总体百分比',
							type: 'map',
							mapType: 'china',
							mapValueCalculation: 'max',
							roam: true,
							label: {
								normal: {
									show: true
								},
								emphasis: {
									show: true
								}
							},
							data: data.data.femaleallper
						},
					];
		geomax["all"] = data.range.all[1];
		geomax["local"] = data.range.local[1];
		geomax["per"] = data.range.per[1];
		geomax["permale"] = data.range.permale[1];
		geomax["permalemin"] = data.range.permale[0];
		geomax["permaleloc"] = data.range.permaleloc[1];
		geomax["perfemale"] = data.range.perfemale[1];
		geomax["perfemaleloc"] = data.range.perfemaleloc[1];
		paperoption['geo'] = option;
		chart['geo'].setOption(option['per']);
		$('#geo-chart').data({'other':'all','now':'per'});
		chart['geo'].dispatchAction({
			type: 'legendSelect',
			name: '地区总人数'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '男性数'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '女性数'
		});
		chart['geo'].dispatchAction({
			type: 'legendSelect',
			name: '占总体百分比'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '男性占地区百分比'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '女性占地区百分比'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '男性占总体百分比'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '女性占总体百分比'
		});
		chart['geo'].resize();
		
		chart['geo'].on('legendselectchanged', function (params) {
			var temp = {};
			var div = $('#geo-chart');
			var now = div.data('now'), other = div.data('other');
			if (now == "per") {
				$.each(params.selected, function(i, v){
					if (i != params.name) {
						chart['geo'].dispatchAction({
							type: 'legendUnSelect',
							name: i
						});
					}
				});
				if (params.name == "占总体百分比") {
					temp.visualMap = {
						min: 0,
						max: geomax["per"],
					};
				} else 	if (params.name == "男性占地区百分比") {
					temp.visualMap = {
						min: geomax["permalemin"],
						max: geomax["permale"],
					};
				} else 	if (params.name == "女性占地区百分比") {
					temp.visualMap = {
						min: 0,
						max: geomax["perfemale"],
					};
				} else 	if (params.name == "男性占总体百分比") {
					temp.visualMap = {
						min: 0,
						max: geomax["permaleloc"],
					};
				} else 	if (params.name == "女性占总体百分比") {
					temp.visualMap = {
						min: 0,
						max: geomax["perfemaleloc"],
					};
				}
				chart['geo'].setOption(temp);
			} else {
				if (params.name == "地区总人数") {
					$.each(params.selected, function(i, v){
						if (i != params.name) {
							chart['geo'].dispatchAction({
								type: 'legendUnSelect',
								name: i
							});
						}
					});
				} else {
					chart['geo'].dispatchAction({
						type: 'legendUnSelect',
						name: '地区总人数'
					});
				}
				if (params.name == "地区总人数") {
					console.log(geomax["local"]);
					temp.visualMap = {
						min: 0,
						max: geomax["local"],
					};
					chart['geo'].setOption(temp);
				} else {
					temp.visualMap = {
						min: 0,
						max: geomax["all"],
					};
					chart['geo'].setOption(temp);
				}
			}
		});
		$('#geo-china').html('问卷人数：'+data.data.china.all+' （男性票数：'+data.data.china.male+'，女性票数：'+data.data.china.female+'）');
		$('#geo-japan').html('问卷人数：'+data.data.text[35].all+' （男性票数：'+data.data.text[35].male+'，女性票数：'+data.data.text[35].female+'）');
		$('#geo-asia').html('问卷人数：'+data.data.text[36].all+' （男性票数：'+data.data.text[36].male+'，女性票数：'+data.data.text[36].female+'）');
		$('#geo-northamerica').html('问卷人数：'+data.data.text[37].all+' （男性票数：'+data.data.text[37].male+'，女性票数：'+data.data.text[37].female+'）');
		$('#geo-southamerica').html('问卷人数：'+data.data.text[38].all+' （男性票数：'+data.data.text[38].male+'，女性票数：'+data.data.text[38].female+'）');
		$('#geo-oceania').html('问卷人数：'+data.data.text[39].all+' （男性票数：'+data.data.text[39].male+'，女性票数：'+data.data.text[39].female+'）');
		$('#geo-europa').html('问卷人数：'+data.data.text[40].all+' （男性票数：'+data.data.text[40].male+'，女性票数：'+data.data.text[40].female+'）');
		$('#geo-africa').html('问卷人数：'+data.data.text[41].all+' （男性票数：'+data.data.text[41].male+'，女性票数：'+data.data.text[41].female+'）');
		$('#geo-other').html('问卷人数：'+data.data.text[42].all+' （男性票数：'+data.data.text[42].male+'，女性票数：'+data.data.text[42].female+'）');
	});
	
	

	var nowdiv = [], loaddiv = [];
	var maxsectio = 5;
	var paperDiv = $('#paper-div');
	for (var k = 1; k <= maxsectio; k++) {
		var sec = paperall[k];
		var sectitle = section[k];

		nowdiv[k] = $('<div/>', { 'id'	: 'paper-sec-'+k });
		nowdiv[k].append($('<h3/>').html(sectitle));
		loaddiv[k] = $('<div/>', { 'id'	: 'paper-sec-'+k });
		loaddiv[k].html("载入中...");
		paperDiv.append(nowdiv[k]);
		paperDiv.append(loaddiv[k]);
	}
	for (var k = 1; k <= maxsectio; k++) {
		var sec = paperall[k];
		$.post('api.php?action=make&object=votepaper&text=paper&index='+k, { paper: sec }).done(function (data) {
			for (var i = 0; i < data.data.length; i++) {
				var v = data.data[i];
				var j = i + 1;
				nowdiv[data.index].append($('<table/>', {
									'class'	: 'table footable',
									'id'	: 'paper'+data.index+'-'+j+'Tab',
								}).data({
									'show-toggle'	: false,
									'expand-all'	: true,
									'show-header'	: false,
								})
					.append($('<thead/>', {
									'class'	: 'footable-header'
								})
						.append($('<tr/>')
							.append($('<th/>').html('问卷：'+v.quest.title))
							.append($('<th/>', {'style': 'display: none;'}).html('图表说明'))
							.append($('<th/>', {'style': 'display: none;'}).html('图表'))))
					.append($('<tbody/>')
						.append($('<tr/>', {
								'class'	: 'footable-detail-row clickable-row',
								'id'	: 'paper'+data.index+'-'+j+'Header'
								}).data({ 'toggle': 'paper'+data.index+'-'+j })
							.append($('<td/>').html('票数：'+v.total.all+' （男性票数：'+v.total.male+'，女性票数：'+v.total.female+'）'))
							.append($('<td/>', {'style': 'display: none;'}))
							.append($('<td/>', {'style': 'display: none;'})))
						.append($('<tr/>', {
							'class'	: 'footable-detail-row',
							'id'	: 'paper'+data.index+'-'+j+'Tr'
							})
							.append($('<td/>', { 'colspan': 3 })
								.append($('<table/>', {'class': 'footable-details table'})
									.append($('<tbody/>')
										.append($('<tr/>')
											.append($('<td/>', {
													'style': 'display: table-cell;'
												})
												.append($('<div/>', {
														'class': 'callout callout-info'
													})
													.append($('<h4/>').html('说明'))
													.append($('<ul/>')
														.append($('<li/>').html('该图表显示问题「'+v.quest.title+'」的答案。'))
														.append($('<li/>').html('如果出现无记录的人数显示则说明存在极少数问卷信息缺损的情况。'))
														.append($('<li/>').html('表格可在扇形图和柱形图之间切换显示。<br>点击图表顶部的图例可以隐藏或显示一类数据。'))))))
										.append($('<tr/>')
											.append($('<td/>', {
													'class': 'type-change-row',
													'style': 'display: table-cell;'
												}).data({ 'div': 'paper'+data.index+'-'+j+'-chart', 'chart': 'paper'+data.index+'-'+j }).html('点击这里切换图表类型')
												))
										.append($('<tr/>')
											.append($('<td/>', {
													'style': 'display: table-cell;'
												})
												.append($('<div/>', {
													'class'	: 'chart-div',
													'id'	: 'paper'+data.index+'-'+j+'-chart'
													}
												)))))))))
				);
				chart['paper'+data.index+'-'+j] = echarts.init($('#paper'+data.index+'-'+j+'-chart')[0]);
				option = [];
				if (v.multi != "1") {
					option['pie'] = {
							title: {
								text: v.quest.title,
								show: true,
						        bottom: 5,
						        left: 'center',
						        textStyle: {
						            fontWeight: 'normal',
						            fontSize: 14,
						            color: '#808080'
						        }
							},
							tooltip : {
								trigger: 'item',
								formatter: '{a}<br />{b}: {c}（{d}）'
							},
							legend: {
								show: false
							},
							toolbox: {
								show: false
							},
							color: ['#c23531','#2f4554', '#61a0a8', '#d48265', '#bda29a','#6e7074', '#546570', '#c4ccd3'],
							series : [
										{
											name:'性别',
											type: 'pie',
											radius: ['40%', '60%'],
											selectedMode: 'single',
											label: {
												normal: {
													show: false
												}
											},
											itemStyle: {
												normal: {
													color: ['#91c7ae','#749f83']
												}
											},
											z: 2,
											data:v.outside
										},
										{
											name:'问题回答',
											type: 'pie',
											radius: [0, '50%'],
											selectedMode: 'single',
											label: {
												normal: {
													show: true,
													position: 'outside'
												}
											},
											labelLine: {
												normal: {
													show: true,
													length: 50,
													position: 'outside'
												}
											},
											z: 3,
											data:v.inside
										}
									]
						};
				} else {
					option["radar"] = {
							color: ['#c23531','#2f4554', '#61a0a8', '#ca8622', '#4D3900', '#749f83', '#546570', '#91c7ae', '#c4ccd3', '#d48265', '#6e7074'],
							title: {
								text: v.quest.title,
								show: true,
						        bottom: 5,
						        left: 'center',
						        textStyle: {
						            fontWeight: 'normal',
						            fontSize: 14,
						            color: '#808080'
						        }
							},
							tooltip: {},
							legend: {
								data: ['总数比例', '男性比例', '女性比例', '男性相对比例', '女性相对比例']
							},
							radar: {
								// shape: 'circle',
								indicator: []
							},
							series: [
							   {
									name: '票数',
									type: 'radar',
									data : [
											{
												value : v.percent.all,
												name : '总数比例'
											},
											{
												value : v.percent.maleall,
												name : '男性比例'
											},
											 {
												value : v.percent.male,
												name : '男性相对比例'
											},
											 {
												value : v.percent.femaleall,
												name : '女性比例'
											},
											 {
												value : v.percent.female,
												name : '女性相对比例'
											}
										]
							   }
							]
						};
					$.each(v.item, function(i, item) {
						option["radar"].radar.indicator[i] = {
							name: item,
							max: 100
						};
					});
				}
				option['bar'] = {
					title: {
						text: v.quest.title,
						show: true,
				        bottom: 5,
				        left: 'center',
				        textStyle: {
				            fontWeight: 'normal',
				            fontSize: 14,
				            color: '#808080'
				        }
					},
					tooltip : {
						trigger: 'axis',
						axisPointer : {
							type : 'shadow'
						}
					},
					grid: {
						left: 200
					},
					legend: {
						data: ['男性', '女性', '总数']
					},
					toolbox: {
						show: false
					},
					calculable : true,
					xAxis : [
						{
							type: 'value'
						}
					],
					yAxis : [
						{
							type : 'category',
							data : v.quest.value
						}
					],
					series : [
								{
									name: '男性',
									type: 'bar',
									stack: '总量',
									label: {
										normal: {
											show: true,
											position: 'insideRight'
										}
									},
									data:v.data.male
								},
								{
									name: '女性',
									type: 'bar',
									stack: '总量',
									label: {
										normal: {
											show: true,
											position: 'insideRight'
										}
									},
									data:v.data.female
								},
								{
									name: '总数',
									type: 'bar',
									label: {
										normal: {
											show: true,
											position: 'insideRight'
										}
									},
									data:v.data.all
								}
							]
				};
				paperoption['paper'+data.index+'-'+j] = option;
				if (v.multi != "1") {
					$('#paper'+data.index+'-'+j+'-chart').data({'other':'bar','now':'pie'});
					chart['paper'+data.index+'-'+j].setOption(option['pie']);
				} else {
					$('#paper'+data.index+'-'+j+'-chart').data({'other':'bar','now':'radar'});
					chart['paper'+data.index+'-'+j].setOption(option['radar']);
					chart['paper'+data.index+'-'+j].dispatchAction({
						type: 'legendUnSelect',
						name: '男性相对比例'
					});
					chart['paper'+data.index+'-'+j].dispatchAction({
						type: 'legendUnSelect',
						name: '女性相对比例'
					});

					chart['paper'+data.index+'-'+j].on('legendselectchanged', function (params) {
						if (params.selected[params.name] == true) {
							if (params.name == "男性比例" || params.name == "女性比例") {
								this.dispatchAction({
									type: 'legendSelect',
									name: (params.name == "男性比例" ? '女性比例' : '男性比例')
								});
								var t = this;
								$.each(params.selected, function(i, v){
									if (i == "男性相对比例" || i == "女性相对比例") {
										t.dispatchAction({
											type: 'legendUnSelect',
											name: i
										});
									}
								});
							} else if (params.name == "男性相对比例" || params.name == "女性相对比例") {
								this.dispatchAction({
									type: 'legendSelect',
									name: (params.name == "男性相对比例" ? '女性相对比例' : '男性相对比例')
								});
								var t = this;
								$.each(params.selected, function(i, v){
									if (i == "男性比例" || i == "女性比例") {
										t.dispatchAction({
											type: 'legendUnSelect',
											name: i
										});
									}
								});
							}
						}
					});
				}
				chart['paper'+data.index+'-'+j].resize();
			};
			loaddiv[data.index].hide();
		});
	}
	crossDiv.on("click", "#button", function() {
		var quest1 = crossSelect[0].getValue();
		var quest2 = crossSelect[1].getValue();
		$("#alert-success").hide("slow");
		$("#alert-cross").hide("slow");
		$("#alert-info").hide("slow");
		$("#alert-danger").hide("slow");
		$("#cross-change").hide("slow");
		if (quest1 == "" || quest2 == "" || quest1 == quest2) {
			$("#alert-warning").show("slow");
			return;
		} else {
			$("#alert-warning").hide("slow");
		}
		
		$.post('api.php?action=make&object=votepaper&text=paper', { quest1: quest1, quest2: quest2 }).done(function (data) {
			console.log(data);
			if (data.cross == true) {
				$("#alert-cross").show("slow");
				return;
			}
			var v = data.data;
			chart['cross'] = echarts.init($('#cross-chart')[0]);
			option = [];
			if (v.multi1 != "1") {
				option['pie'] = {
						title: {
							text: data.title1,
							show: true,
					        bottom: 5,
					        left: 'center',
					        textStyle: {
					            fontWeight: 'normal',
					            fontSize: 14,
					            color: '#808080'
					        }
						},
						tooltip : {
							trigger: 'item',
							formatter: '{a}<br />{b}: {c}（{d}）'
						},
						legend: {
							show: false
						},
						toolbox: {
							show: false
						},
						series : [
									{
										name:'问题2回答',
										type: 'pie',
										radius: ['40%', '60%'],
										selectedMode: 'single',
										label: {
											normal: {
												show: false
											}
										},
										z: 2,
										data: v.outside
									},
									{
										name:'问题1回答',
										type: 'pie',
										radius: [0, '50%'],
										selectedMode: 'single',
										label: {
											normal: {
												show: true,
												position: 'outside'
											}
										},
										labelLine: {
											normal: {
												show: true,
												length: 50,
												position: 'outside'
											}
										},
										z: 3,
										data: v.inside
									}
								]
					};

				option['bar'] = {
					title: {
						text: data.title1,
						show: true,
				        bottom: 5,
				        left: 'center',
				        textStyle: {
				            fontWeight: 'normal',
				            fontSize: 14,
				            color: '#808080'
				        }
					},
					tooltip : {
						trigger: 'axis',
						axisPointer : {
							type : 'shadow'
						}
					},
					grid: {
						left: 200
					},
					legend: {
						data: v.item2
					},
					toolbox: {
						show: false
					},
					calculable : true,
					xAxis : [
						{
							type: 'value'
						}
					],
					yAxis : [
						{
							type : 'category',
							data : v.item1
						}
					],
					series : []
				};
				$.each(v.item2, function(i, value) {
					option['bar']['series'][i] = {
						name: value,
						type: 'bar',
						stack: '总量',
						label: {
							normal: {
								show: true,
								position: 'insideRight'
							}
						},
						data:v.data[i]
					};
				});
			} else {
				option["radar"] = {
						color: ['#c23531','#2f4554', '#61a0a8', '#ca8622', '#4D3900', '#749f83', '#546570', '#91c7ae', '#c4ccd3', '#d48265', '#6e7074'],
						title: {
							text: '问题1：'+data.title1,
							subtext: '问题2：'+data.title2+'（占问题1项目人数比例）',
							show: true,
					        bottom: 10,
					        left: 'center',
					        textStyle: {
					            fontWeight: 'normal',
					            fontSize: 14,
					            color: '#808080'
					        },
					        subtextStyle: {
					            fontWeight: 'normal',
					            fontSize: 13,
					            color: '#909090'
					        }
						},
						tooltip: {},
						legend: {
					        data: ['占项目比', '占回答比'],
					        itemGap: 20,
					        selectedMode: 'single'
						},
						radar: {
							// shape: 'circle',
							indicator: []
						},
						series: [
						   {
								name: '占项目比',
								type: 'radar',
								data : []
						   },
						   {
								name: '占回答比',
								type: 'radar',
								data : []
						   }
						]
					};
				$.each(v.item2, function(i, item) {
					option["radar"].series[0].data[i] = {
						value : v.percent[i],
						name : item
					};
					option["radar"].series[1].data[i] = {
							value : v.percentall[i],
							name : item
						};
				});
				option["radar"].series[0].data[v.item2.length] = {
					value : v.percent.all,
					name : '总数'
				};
				$.each(v.item1, function(i, item) {
					option["radar"].radar.indicator[i] = {
						name: item,
						max: 100
					};
				});

				option['bar'] = {
					title: {
						text: data.title1,
						subtext: data.title2,
						show: true,
				        bottom: 0,
				        left: 'center',
				        textStyle: {
				            fontWeight: 'normal',
				            fontSize: 14,
				            color: '#808080'
				        },
				        subtextStyle: {
				            fontWeight: 'normal',
				            fontSize: 13,
				            color: '#909090'
				        }
					},
					tooltip : {
						trigger: 'axis',
						axisPointer : {
							type : 'shadow'
						}
					},
					grid: {
						left: 200
					},
					legend: {
						data: v.item2
					},
					toolbox: {
						show: false
					},
					calculable : true,
					xAxis : [
						{
							type: 'value'
						}
					],
					yAxis : [
						{
							type : 'category',
							data : v.item1
						}
					],
					series : []
				};
				$.each(v.item2, function(i, value) {
					option['bar']['series'][i] = {
						name: value,
						type: 'bar',
						stack: '总量',
						label: {
							normal: {
								show: true,
								position: 'insideRight'
							}
						},
						data:v.data[i]
					};
				});
			}
			paperoption['cross'] = option;
			if (v.multi1 != "1") {
				$('#cross-chart').data({'other':'bar','now':'pie'});
				chart['cross'].setOption(option['pie'], true);
			} else {
				$('#cross-chart').data({'other':'bar','now':'radar'});
				chart['cross'].setOption(option['radar'], true);
			}

			chart['cross'].resize();

			$("#cross-change").show("slow");
			$("#alert-success").show("slow");
			$("#alert-info").hide("slow");
			$("#alert-danger").hide("slow");
			$("#alert-warning").hide("slow");
			$("#alert-cross").hide("slow");
		});
	});
		
	
	
	$(window).resize(function() {
		$.each(chart, function(i, c) {
			c.resize();
		});
	});
	
});