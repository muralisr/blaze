var imagesInViewPort = []



function isElementInViewport (el) {
    //special bonus for those using jQuery
    if (typeof jQuery === "function" && el instanceof jQuery) {
        el = el[0];
    }
    var rect = el.getBoundingClientRect();
    var topIsVisible = rect.top >= 0 && (rect.top <= (window.innerHeight || document.documentElement.clientHeight));
	var botIsVisible = rect.top < 0 && rect.bottom >= 0;
	var vertInView = topIsVisible || botIsVisible;

	var leftIsVisible = rect.left >= 0 && (rect.left <= (window.innerWidth || document.documentElement.clientWidth));
	var rightIsVisible = rect.left < 0 && rect.right >= 0;
	var horzInView = leftIsVisible || rightIsVisible;

	return vertInView && horzInView;
}


function getCriticalRequests() {
    console.log("inside getCriticalRequests")
    var importantRequests = []
    importantRequests = imagesInViewPort.map(function(url) {return url;});
    if (typeof(urlRequestors) == 'undefined' || urlRequestors == null) return importantRequests;
    urlRequestors.forEach(function(k) {
        if (imagesInViewPort.indexOf(k.url) >= 0) {
            importantRequests = importantRequests.concat(k.initiator)
        }
    })
    return importantRequests
}


function findAndPrintImagesInViewport(ele) {
	console.log("in findandprintimagesinviewport");
    ele.querySelectorAll('*').forEach(function(node) {
        try {
            if (isElementInViewport(node)) {
                var url = null;
                if(node.tagName == "IMG") {
                    if (typeof node.href != 'undefined') {
                        url = node.href;
                    }
                    if(typeof node.src != 'undefined') {
                        url = node.src;
                    }
                    if (url != null) {
                        imagesInViewPort.push(url)
                    }
            } else {
                var style = window.getComputedStyle(node)
                for (var i = style.length - 1; i >= 0; i--) {
                    var cssName = style[i]
                    var cssPropertyValue = style.getPropertyValue(cssName)
                    if (cssPropertyValue.indexOf("url") >= 0) {
                        var potentialURL = cssPropertyValue;
                        var startIndex = potentialURL.indexOf('url(')
                        var urlWithSpace = false;
                        if (startIndex < 0) {
                            startIndex = potentialURL.indexOf('url (')
                            urlWithSpace = true;
                        } 
                        if (startIndex < 0) {
                            continue;
                        }
                        var endIndex = potentialURL.indexOf(')', startIndex)
                        if (endIndex < 0) {
                            continue
                        }
                        var potentialURL = potentialURL.substring(startIndex + (urlWithSpace ? 5 : 4), endIndex)
                        var t=potentialURL.length;
                        if (potentialURL.charAt(0)=='"'||potentialURL.charAt(0)=="'") {
                            potentialURL = potentialURL.substring(1);
                            t--;
                        }
                        if (potentialURL.charAt(t-1)=='"'||potentialURL.charAt(t-1)=="'") {
                            potentialURL = potentialURL.substring(0,t-1);
                        }
    
                        var link = document.createElement("a");
                        link.href = potentialURL;
                        if(potentialURL.indexOf("data:image") < 0)
                            imagesInViewPort.push(link.href)
                    }
                }
            }  
            }           
        } catch (error) {
            console.error("ignoring node due to error ", error)
        }

    });
    var answer = getCriticalRequests()
	console.log("writing to alohamora output");
    console.log(JSON.stringify({'alohomora_output': answer}))
}

function getAllUrlsFromInlineStyles() {
	console.log("getting urls from inline styles in " + document.URL);
    var css = [];
	console.log("1 " + document.URL);
    for (var i=0; i<document.styleSheets.length; i++)
    {
	    console.log("2 " + document.URL);
	try {
        var sheet = document.styleSheets[i];
	    
	    if (!('cssRules' in sheet || 'rules' in sheet)){ console.log("continueing " + document.URL);continue;}
        var rules = ('cssRules' in sheet)? sheet.cssRules : sheet.rules;
	    console.log("3 " + document.URL);

        if (rules)
        {
		console.log("4 " + document.URL);

            css.push('\n/* Stylesheet : '+(sheet.href||'[inline styles]')+' */');
		console.log("5 " + document.URL);

            for (var j=0; j<rules.length; j++)
            {
		    console.log("6 " + document.URL);

                var rule = rules[j];
                if ('cssText' in rule) {
                    css.push(rule.cssText);
			console.log("7 " + document.URL);
		}
                else {
                    css.push(rule.selectorText+' {\n'+rule.style.cssText+'\n}\n');
			console.log("8 " + document.URL);
		}
		    console.log("9 " + document.URL);
            }
		console.log("10 " + document.URL);
        }
    }
	catch(error) {
		console.log("skipping sheet due to error ", error)
	}
}
	console.log("11 " + document.URL);

	console.log("going to do regex in " + document.URL);
    var cssInline = css.join('\n')+'\n';
	console.log("cssinline is below in " + document.URL)
	console.log(cssInline)
	console.log("cssinline is above in " + document.URL)
    var regExpr = new RegExp(/url\(.*?\)/, 'gi')
    var listOfUrlsInCSS = cssInline.match(regExpr)
	console.log("listofcss is below\n")
	console.log(listOfUrlsInCSS)
	console.log("\nlistofcss is above")
    listOfUrlsInCSS.forEach(function(value) {
        if (value.indexOf("url") >= 0) {
		console.log("found a potential url")
            var potentialURL = value;
            var startIndex = potentialURL.indexOf('url(')
            var urlWithSpace = false;
            if (startIndex < 0) {
                startIndex = potentialURL.indexOf('url (')
                urlWithSpace = true;
            } 
            if (startIndex < 0) {
                return;
            }
            var endIndex = potentialURL.indexOf(')', startIndex)
            if (endIndex < 0) {
                return
            }
            var potentialURL = potentialURL.substring(startIndex + (urlWithSpace ? 5 : 4), endIndex)
            var t=potentialURL.length;
            if (potentialURL.charAt(0)=='"'||potentialURL.charAt(0)=="'") {
                potentialURL = potentialURL.substring(1);
                t--;
            }
            if (potentialURL.charAt(t-1)=='"'||potentialURL.charAt(t-1)=="'") {
                potentialURL = potentialURL.substring(0,t-1);
            }

            var link = document.createElement("a");
            link.href = potentialURL;
            if(potentialURL.indexOf("data:image") < 0)
                imagesInViewPort.push(link.href)
        }
    })
}

window.addEventListener('load', function (event) {
    try {
	console.log("on page load fired");
        getAllUrlsFromInlineStyles()
        findAndPrintImagesInViewport(document)
        var listOfIframes = document.querySelectorAll("iframe");
        for (var index = 0; listOfIframes && index < listOfIframes.length; index++) {
            const iframeElement = listOfIframes[index];
            if(typeof(iframeElement) == 'undefined') {
                continue;
            }
            if(iframeElement && isElementInViewport(iframeElement)) {
                try {
                    var innerDoc = (iframeElement.contentDocument) ? iframeElement.contentDocument : iframeElement.contentWindow.document;    
                    findAndPrintImagesInViewport(innerDoc)
                } catch (error) {
                    console.error('avoid processing iframe due to an exception ', error)
                }
            }
        }    
    } catch (error) {
        console.error("skipping due to error ", error)
    }    
  });

