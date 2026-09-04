/**
 * Charts and other
 */
var chart = {};
var paperoption = [];
var geomax = [];

var hobAry = [
			 	'eda8afdfc227577a7ff0c299b7e7bYd0zSJ6b7e7',
				'36d16e4c63906453136ac55b9ed9UZcdo5Of9ed9',
			   	'047ea047fd4115104f07cec0e173zenK10r0e173',
				'e9689867795db5e30258902dbf9dg1SBOFMXbf9d',
				'8d5ef8cc0bdc503c8e0c30d62e51avmJ216Z2e51',
				'5436376bc2e27afc23b18f45bgXFFtpk3a306d5d',
				'c80c82d38b4a37b6c789f722035dZe9IDQdk035d',
				'9959d721fb7461ea46d60efc4096kBgdoj494096',
				'78b817aec074f7593537c69fa84aRiDyP2VYa84a',
				'32205a96cf323ad843283fdfa947zEx2vizia947',
				'615a0dad1275606ca2259c723372Ctsd4vyT3372',
				'ffc7c35fce41b2c0f0f4f3eb163anCxGRMtc163a',
				'c9c6399841dbdd88e1bc22031b548zgNIDKR1b54',
				'c5818ad103f5321952e69665f4b6byzONUhaf4b6'
		];

$(document).ready(function(){
	$('#list').footable({
		"breakpoints": {
			"xs": 180, // extra small
			"sm": 400, // small
			"md": 600, // medium
			"lg": 1024, // large
			"xl": 1100 // extra large
		}
	});
	
	$('.clickable-row').on('click', function(){
		var toggle = $(this).data('toggle');
		$('#'+toggle+'Tr').toggle('slow');
	});

	$('#paper-div').on('click', '.type-change-row', function(){
		var div = $('#'+$(this).data('div'));
		var now = div.data('now'), other = div.data('other');
		var thischart = $(this).data('chart');
		chart[thischart].setOption(paperoption[thischart][other], true);
		div.data({
			'now': other,
			'other': now
		});
		if (thischart == "geo") {
			if (now == "per") {
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '地区总人数'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '地区投票数'
				});
			} else {
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '占地区男性百分比'
				});
				chart['geo'].dispatchAction({
					type: 'legendUnSelect',
					name: '占地区女性百分比'
				});
			}
		}
	});

	$.get('api.php?action=make&object=votedate&text='+type+'&id='+id).done(function (data) {
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
					data: data.item,
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
		$.each(data.item, function(i, item) {
			option.series[i] = {
							name: item,
							type: 'line',
							data: data.data[i]
						};
		});
		chart['progress'] = echarts.init($('#progress-chart')[0]);
		chart['progress'].setOption(option);
	});

	chart['sex'] = echarts.init($('#sex-chart')[0]);
	$.get('api.php?action=make&object=votesex&text='+type+'&id='+id).done(function (data) {
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
					data: data.item
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
	$.get('api.php?action=make&object=votegeo&text='+type+'&id='+id).done(function (data) {
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
		if (data.type == 'all') {
			option["per"].series = option["all"].series = [
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
		} else {
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
									name:'地区投票数',
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
									data: data.data.sum
								},
								{
									name:'男性票数',
									type: 'map',
									mapType: 'china',
									mapValueCalculation: 'sum',
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
									name:'女性票数',
									type: 'map',
									mapType: 'china',
									mapValueCalculation: 'sum',
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
           								name:'占地区百分比',
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
           								name:'占地区男性百分比',
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
           								name:'占地区女性百分比',
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
           						];
		}
		geomax["all"] = data.range.all[1];
		geomax["local"] = data.range.local[1];
		geomax["per"] = data.range.per[1];
		paperoption['geo'] = option;
		chart['geo'].setOption(option['per']);
		$('#geo-chart').data({'other':'all','now':'per'});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '占地区男性百分比'
		});
		chart['geo'].dispatchAction({
			type: 'legendUnSelect',
			name: '占地区女性百分比'
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
				temp.visualMap = {
					min: 0,
					max: geomax["per"],
				};
			} else {
				if (params.name == "地区总人数" || params.name == "地区投票数" ) {
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
					chart['geo'].dispatchAction({
						type: 'legendUnSelect',
						name: '地区投票数'
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
		
		$('#geo-china').html('投票人数：'+data.data.china.sum+' （男性票数：'+data.data.china.male+'，女性票数：'+data.data.china.female+'），该地区总票数：'+data.data.china.all);
		$('#geo-japan').html('投票人数：'+data.data.text[35].sum+' （男性票数：'+data.data.text[35].male+'，女性票数：'+data.data.text[35].female+'），该地区总票数：'+data.data.text[35].all);
		$('#geo-asia').html('投票人数：'+data.data.text[36].sum+' （男性票数：'+data.data.text[36].male+'，女性票数：'+data.data.text[36].female+'），该地区总票数：'+data.data.text[36].all);
		$('#geo-northamerica').html('投票人数：'+data.data.text[37].sum+' （男性票数：'+data.data.text[37].male+'，女性票数：'+data.data.text[37].female+'），该地区总票数：'+data.data.text[37].all);
		$('#geo-southamerica').html('投票人数：'+data.data.text[38].sum+' （男性票数：'+data.data.text[38].male+'，女性票数：'+data.data.text[38].female+'），该地区总票数：'+data.data.text[38].all);
		$('#geo-oceania').html('投票人数：'+data.data.text[39].sum+' （男性票数：'+data.data.text[39].male+'，女性票数：'+data.data.text[39].female+'），该地区总票数：'+data.data.text[39].all);
		$('#geo-europa').html('投票人数：'+data.data.text[40].sum+' （男性票数：'+data.data.text[40].male+'，女性票数：'+data.data.text[40].female+'），该地区总票数：'+data.data.text[40].all);
		$('#geo-africa').html('投票人数：'+data.data.text[41].sum+' （男性票数：'+data.data.text[41].male+'，女性票数：'+data.data.text[41].female+'），该地区总票数：'+data.data.text[41].all);
		$('#geo-other').html('投票人数：'+data.data.text[42].sum+' （男性票数：'+data.data.text[42].male+'，女性票数：'+data.data.text[42].female+'），该地区总票数：'+data.data.text[42].all);
	});
	
	$.post('api.php?action=make&object=votepaper&text='+type+'&id='+id, { paper: hobAry }).done(function (data) {
		$.each(data.data, function(i, v) {
			var j = i + 1, div = [];
			var paperDiv = $('#paper-div');
			div[j] = 
			paperDiv.append($('<table/>', {
								'class'	: 'table footable',
								'id'	: 'paper'+j+'Tab',
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
							'id'	: 'paper'+j+'Header'
							}).data({ 'toggle': 'paper'+j })
						.append($('<td/>').html('票数：'+vote+' （男性票数：'+male+'，女性票数：'+female+'）'))
						.append($('<td/>', {'style': 'display: none;'}))
						.append($('<td/>', {'style': 'display: none;'})))
					.append($('<tr/>', {
						'class'	: 'footable-detail-row',
						'id'	: 'paper'+j+'Tr'
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
											}).data({ 'div': 'paper'+j+'-chart', 'chart': 'paper'+j }).html('点击这里切换图表类型')
											))
									.append($('<tr/>')
										.append($('<td/>', {
												'style': 'display: table-cell;'
											})
											.append($('<div/>', {
												'class'	: 'chart-div',
												'id'	: 'paper'+j+'-chart'
												}
											)))))))))
			);
			chart['paper'+j] = echarts.init($('#paper'+j+'-chart')[0]);
			option = [];
			if (v.multi != "1") {
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
							data: v.item
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
						title: {
							text: '问卷图表',
							show: false
						},
						tooltip: {},
						legend: {
							data: ['总数', '男性', '女性']
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
											value : v.data.all,
											name : '总数'
										},
										{
											value : v.data.male,
											name : '男性'
										},
										 {
											value : v.data.female,
											name : '女性'
										}
									]
						   }
						]
					};
				$.each(v.item, function(i, item) {
					option["radar"].radar.indicator[i] = {
						name: item,
						max: vote
					};
				});
			}
			option['bar'] = {
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
			paperoption['paper'+j] = option;
			if (v.multi != "1") {
				chart['paper'+j].setOption(option['pie']);
				$('#paper'+j+'-chart').data({'other':'bar','now':'pie'});
			} else {
				chart['paper'+j].setOption(option['radar']);
				$('#paper'+j+'-chart').data({'other':'bar','now':'radar'});
			}
			chart['paper'+j].resize();
		});
	});
	
	
	$(window).resize(function() {
		$.each(chart, function(i, c) {
			c.resize();
		});
	});
	
});